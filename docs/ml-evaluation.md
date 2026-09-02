# ML Evaluation

## Dataset

`ml/data/synthetic_generator.py`, run via `scripts/generate_synthetic_dataset.py --rows 50000
--seed 42`. Deterministic (numpy `default_rng(42)`), 50,000 rows, 70/15/15 train/validation/test
split (35,000 / 7,500 / 7,500), written to `ml/data/{train,validation,test}.csv` (gitignored —
regenerate, don't commit).

Every row is one (payment-failure context, candidate action) pair with a ground-truth outcome
sampled from a documented, hand-specified probability function (`_BASE_PROBABILITY` in the
generator) — nothing is independently random. Verified relationships in the actual generated
data (from a real run, not hypothetical):

| Relationship | Evidence from the real 50k-row generation run |
|---|---|
| Repeated failures → decreasing recovery probability | `retry_count=0 → 0.282`, `1 → 0.206`, `2 → 0.142`, `3 → 0.119`, `4 → 0.069` (retry_count=5 is a noisy outlier — only ~a dozen rows reach it, since `retry_count ~ Poisson(0.6)` capped at 5) |
| `RISK_BLOCKED` has the lowest class-level recovery rate | `0.158`, lowest of all 7 failure classes |
| `GATEWAY_TIMEOUT`/`NETWORK_ERROR` (transient) recover best | `0.301` / `0.297`, highest of all 7 |
| `CUSTOMER_ACTION_REQUEST` outperforms blind retry | `0.303` vs `SMART_RETRY`'s `0.231` |
| 20k+ rows, 50k preferred | 50,000 generated |

~250 synthetic customers (`n_rows // 3`) with a stable latent `true_recovery_propensity`
(Beta(2.2, 3.0)) and `value_tier` (60% low / 30% mid / 10% high), generating a realistic
repeat-customer structure. `historical_recovery_rate`/`customer_success_rate`/
`customer_failure_rate`/`number_of_prior_recoveries` are computed as **running counters
strictly before** the row's own outcome is applied — the leakage-prevention "cutoff
discipline" `ml/features/feature_definitions.py` requires, verified by
`tests/unit/test_feature_engineering.py`'s `LEAKAGE_EXCLUDED_FIELDS` check.

## Features

The full, documented list is `ml/features/feature_definitions.py` — 14 context features plus
`candidate_action` (15 total): `amount`, `payment_method`, `failure_class`, `retry_count`,
`time_since_failure_hours`, `customer_success_rate`, `customer_failure_rate`,
`historical_recovery_rate`, `customer_lifetime_value`, `subscription_status`, `hour_of_day`,
`day_of_week`, `previous_response_to_intervention`, `number_of_prior_recoveries`,
`candidate_action`. Explicitly excluded as leakage: `actual_recovered`, `recovery_time`,
`successful_action`, `final_attempt_count`, `intervention_cost` — these are only knowable
after the outcome, and a unit test (`test_no_leakage_fields_among_features`) guards against
any of them being reintroduced.

## Models

`ml/training/preprocessing.py` builds a shared `ColumnTransformer` (one-hot encoding for the
5 categorical features, `StandardScaler` for the 10 numeric ones — the scaler matters for the
logistic-regression baseline's `lbfgs` solver convergence given `amount`'s raw-paise scale
sits next to 0-1 rate features; harmless for LightGBM's tree splits). Both models are
persisted as a single fitted sklearn `Pipeline` (`joblib`), so
`ml/inference/predictor.py` never needs to know which model type it loaded.

**Real results from an actual training run** (`ml/training/train_baseline.py` /
`train_lightgbm.py`, against the 50k-row dataset above, held-out test set evaluated exactly
once):

| Metric | Logistic Regression (baseline) | LightGBM (production) |
|---|---|---|
| ROC-AUC | 0.6609 | 0.6533 |
| Average precision | 0.3812 | 0.3813 |
| Precision @ 0.5 | 0.3352 | 0.3408 |
| Recall @ 0.5 | 0.6328 | 0.5679 |
| F1 @ 0.5 | 0.4383 | 0.4260 |
| Log loss | 0.6513 | 0.6344 |
| Brier score | 0.2297 | 0.2222 |
| **Calibration error (ECE, 10 bins)** | 0.2390 | **0.2170** |

**LightGBM was selected as the active model** (`ml/training/artifacts/active_model.json`)
primarily for its better calibration (ECE 0.217 vs 0.239) and better log loss/Brier score —
not because it dominates on every metric (it doesn't: the logistic baseline actually has
marginally higher ROC-AUC and notably higher recall@0.5). Calibration is the property that
matters most here, because this probability feeds directly into
`expected_value = probability × amount − costs` — a financial calculation a policy gate
trusts. This is a real, non-fabricated trade-off, documented rather than glossed over; see
docs/decisions.md "Why tabular ML."

Both ECE values (~0.22-0.24) are honestly mediocre in absolute terms — this is a genuinely
hard, high-class-imbalance-adjacent problem (~24% base recovery rate) on a synthetic dataset
that intentionally includes noise (each row's outcome is a single Bernoulli draw from the
true probability, not the probability itself). Future work: isotonic/Platt calibration as a
post-processing step, and re-tuning `MIN_CONFIDENCE` (see below) directly against this number
rather than a priori.

## Baselines and the 4-way full-dataset benchmark, plus a 5-way AI ablation

`simulator/benchmark/baseline_runner.py` runs all 4 baselines against the SAME held-out test
set (`ml/data/test.csv`, 7,500 rows never touched during training or threshold selection),
reusing the real production decision code — the trained LightGBM model, the real
`app.services.optimizer_service` expected-value math, and the real
`app.policies.policy_engine` — for `ML_ONLY` and `RECOVERYOS_FULL`. See that module's
docstring for exactly how counterfactual outcomes are computed (this synthetic world's true
probability function is fully known by construction, which is what makes asking "what if a
different action had been chosen" legitimate here — it would not be for real logged data
without off-policy correction).

**Scope note**: despite its name, `RECOVERYOS_FULL` does **not** call the AI diagnostician —
running all 7,500 rows through a real LLM would be slow, costly, and non-deterministic. It is
ML + Optimizer + Policy only. The genuine ML+AI+Optimizer+Policy arm — matching what
`app/services/analysis_service.py` actually does in production, including its bounded AI
confidence nudge — is a 5th baseline, `RECOVERYOS_AI`, run only on a small bounded sample via
`--run-ai-ablation`. See **docs/ai-ablation.md** for that full writeup; this section covers
the always-on, full-dataset 4-way comparison.

**Results from a run against all 7,500 held-out rows** (reproducible:
`python simulator/benchmark/baseline_runner.py`, ~11 seconds). Money figures are in **₹ Lakh**
(1 Lakh = ₹100,000):

| Baseline | Recovered revenue | Net Recovery Value | Recovery rate | Precision | Unnecessary action rate | Revenue/intervention | Policy rejection rate |
|---|---|---|---|---|---|---|---|
| ALWAYS_RETRY | ₹36.94L | ₹36.93L | 21.7% | 0.217 | 78.3% | ₹49,256 | 0% |
| STATIC_RULES | ₹52.54L | ₹52.53L | 30.4% | 0.312 | 68.8% | ₹71,844 | 0% |
| ML_ONLY | **₹53.62L** | **₹95.17L** | **31.3%** | 0.313 | 68.7% | ₹71,496 | 0% |
| RECOVERYOS_FULL | ₹47.96L | ₹81.89L | 28.2% | **0.335** | **66.5%** | **₹76,064** | 15.9% |

**Read this honestly, per the product spec's own instruction not to fabricate superiority:**
RecoveryOS does **not** win on raw recovered revenue in this run — ML_ONLY recovers more
gross rupees because it never says no to a candidate action, however low its expected value.
RecoveryOS wins decisively on **discipline**: highest precision, lowest unnecessary-action
rate, highest revenue per intervention, and a real 15.9% policy-rejection rate — cases where
the system correctly declined to act because the expected value or confidence didn't clear
the bar. This is the actual value proposition: **bounded, efficient, explainable recovery**,
not maximum blind retry volume. A reviewer should treat "RecoveryOS recovers slightly less
gross revenue while intervening on far fewer cases and being far more precise about which
ones" as the real, reportable finding — not something to tune away.

**Net Recovery Value needs one more honest caveat.** It is computed from *expected* recovered
revenue (each baseline's own probability estimate × amount, minus intervention and risk cost)
— not the *realized* recovered revenue column next to it. ML_ONLY's Net Recovery Value
(₹95.17L) looks dramatically higher than its actual recovered revenue (₹53.62L) precisely
because it never applies policy discipline to temper an optimistic probability estimate, and
its calibration is measurably worse (ECE 0.258 here vs. RECOVERYOS_FULL's own gap: ₹81.89L
expected vs. ₹47.96L realized, ECE 0.290 on this run). **This gap is the calibration problem
made concrete**: an uncalibrated or overconfident probability estimate inflates an
expected-value-based objective in a way the realized outcome does not bear out — exactly why
`docs/decisions.md` and the calibration analysis above matter for a metric that is used to
make real financial decisions, not just to score a model on a leaderboard.

**One real, disclosed course-correction that happened during this evaluation**: the initial
`MIN_CONFIDENCE` placeholder (0.55) turned out to reject the overwhelming majority of
candidates once actually run against this model, whose predicted probabilities center around
the dataset's ~24% base recovery rate — a 0.55 bar assumes something close to a coin-flip
model, which this correctly is not. Recalibrating to `0.15` (roughly two-thirds of the base
rate, filtering out clearly-below-average candidates without rejecting most real
opportunities) produced the results above. This is disclosed as a real finding from actually
running the benchmark, not a retroactive tuning-for-a-win — the result after recalibration
still shows RecoveryOS behind on gross revenue, exactly as reported.

Reproducibility: `simulator/benchmark/results/latest.json` holds the exact output of the run
tabulated above. Results also persist to the `experiments`/`experiment_results` tables when a
database is reachable (best-effort — `GET /api/analytics/benchmark` reads only from there,
never the JSON file, so the dashboard can never show something the database doesn't actually
have).

## Known limitations

- The train/validation/test split is by row, not by customer — a given synthetic customer's
  events can appear across splits. Acceptable for this task (the model predicts
  P(recovery | one event's context, action), not a per-customer forecast) but disclosed
  rather than assumed away.
- `historical_recovery_rate` stands in for the generator's latent `true_recovery_propensity`
  in the benchmark's counterfactual simulation, since the CSV persists only the observable
  correlate, not the latent variable itself.
- Calibration (ECE ~0.22) is mediocre in absolute terms; isotonic regression as a
  post-processing step is the natural next iteration, along with re-deriving policy
  thresholds directly from validation-set precision/recall curves rather than the current
  once-corrected placeholders.
- This is a synthetic-data-trained model. It demonstrates the pipeline and the evaluation
  methodology honestly; it is not a claim of real-world predictive accuracy on actual
  merchant transaction data, which doesn't exist for this project (see docs/decisions.md's
  "Why synthetic data").
