# RecoveryOS — Autonomous Revenue Recovery Control Plane

Built for the **Razorpay AI Buildathon — Track 03: AI Revenue Recovery**.

> RecoveryOS detects revenue at risk, determines the highest-value recovery intervention,
> validates that intervention through deterministic financial safety policies, executes only
> approved actions, and measures the money actually recovered.
>
> **AI proposes. Optimization prioritizes. Policy decides. Executor acts. Ledger proves.**

## Status

**Core pipeline, ML, policy, execution, API, frontend, and benchmark are real and working —
including the full outcome-reconciliation loop for payment-link-driven recovery.** End to
end: webhook ingestion → state reconstruction → revenue signal detection → ML scoring (a real
trained LightGBM model) → AI diagnosis (real Anthropic integration, degrades gracefully
without a key) → optimizer → policy engine (8 real rules) → executor (real Razorpay Payment
Link adapter — every recovery Payment Link is created with `accept_partial: false`, so a
partial payment can never leave a case ambiguously resolved — falls back to a clearly-labeled
simulator without credentials) → **outcome reconciliation** (correlates a NEW payment made
through a recovery Payment Link back to its originating case via the link's `reference_id`,
writes the actual recovered amount exactly once, idempotently) → append-only audit ledger, all
wired together and covered end to end by a real integration test that drives one failed
payment through the entire flow to a reconciled `actual_recovered_amount` and a traceable
audit trail (`backend/tests/integration/test_pipeline_smoke.py`) — **120 test functions / 143
collected test cases, all passing** (see Quickstart). A 4-baseline benchmark (plus an optional
5th AI-inclusive ablation arm, `--run-ai-ablation`) runs against 7,500 held-out synthetic rows
with a fixed seed; results are in [`docs/ml-evaluation.md`](docs/ml-evaluation.md) and
[`docs/ai-ablation.md`](docs/ai-ablation.md) — RecoveryOS wins on **discipline**: highest
precision, lowest unnecessary-action rate, highest revenue per intervention, and a real
policy-rejection rate where it correctly declines low-value actions, rather than on raw
recovered revenue. The React frontend (7 pages) builds and lints cleanly against this API.
`ruff check` and `mypy app` are clean across the whole repository. See
[`docs/limitations.md`](docs/limitations.md) and
[`docs/track-alignment.md`](docs/track-alignment.md) for the precise scope of what's real,
what's simulated, and what's out of scope.

## Why this exists

Revenue loss from failed payments, abandoned checkouts, and failed subscriptions rarely gets a
system-level response — most integrations just show the failure in a dashboard. RecoveryOS
closes the loop: ingest the failure, diagnose why it happened, decide the best-value response
within hard safety limits, act on it through real Razorpay APIs where they exist (and clearly
labeled simulation where they don't), and prove — with an append-only audit trail and a
benchmark against naive baselines — how much money actually came back.

## Architecture at a glance

```
Razorpay Test Mode → Event Ingestion → State Reconstruction → Revenue Signal Engine
   → Recovery Opportunity Engine → [ML Predictor ‖ AI Diagnostician] → Intervention Optimizer
   → Policy Gate → Executor → (Razorpay API | Customer Channel) → Outcome Engine
   → Recovery Ledger → Benchmark Engine
```

Full detail: [`docs/architecture.md`](docs/architecture.md).

**The LLM never touches money.** It classifies and proposes via strict, Pydantic-validated
structured output with zero tool access. A deterministic policy engine is the only thing that
can approve a financial action, and the executor is the only code allowed to call Razorpay or
a customer-communication provider. See [`docs/ai-design.md`](docs/ai-design.md) and
[`docs/decisions.md`](docs/decisions.md).

## Repository layout

```
backend/     FastAPI service — API, domain model, services, policies, executors, integrations
ml/          Synthetic data generation, feature engineering, training, evaluation
simulator/   Failure-storm / scenario generators and the 4-baseline benchmark runner
frontend/    React + TypeScript operations dashboard
docs/        Architecture, track alignment, Razorpay integration notes, ADRs, demo script
scripts/     Operational scripts (migrations, seeding, dataset generation, simulator runs)
```

## Quickstart (local development)

Requires Docker Desktop (or a local PostgreSQL 16+), Python 3.12+, and Node 20+.

```bash
cp .env.example .env          # fill in RAZORPAY_* and LLM_API_KEY if you have them —
                               # everything works in fully-simulated mode without them
docker compose up -d postgres
cd backend
pip install -e ".[dev]"
alembic upgrade head

# Train the ML model (generates a 50k-row synthetic dataset, then trains + evaluates):
python ../scripts/generate_synthetic_dataset.py --rows 50000 --seed 42
python ../ml/training/train_baseline.py
python ../ml/training/train_lightgbm.py     # marks itself active in ml/training/artifacts/

uvicorn app.main:app --reload
# in another shell:
pytest

# frontend, in another shell:
cd ../frontend && npm install && npm run dev   # http://localhost:5173, proxies /api to :8000

# seed a few demo cases for the Command Center/Recovery Queue (optional):
python ../scripts/seed_db.py
# or a bigger failure storm / one named failure-injection scenario:
python ../scripts/run_simulator.py failure-storm --count 100
python ../scripts/run_simulator.py scenario duplicate_webhook

# benchmark, once a model is trained (~11s against the full held-out test set):
python simulator/benchmark/baseline_runner.py
# add --run-ai-ablation for the 5th, AI-inclusive arm on a bounded sample (needs LLM_API_KEY)
```

`GET http://localhost:8000/api/health` should return `{"status": "ok", "db": "ok", ...}`.

> **No Docker/Postgres available?** Unit and smoke tests (state machines, policy engine,
> optimizer math, AI safety, ML inference against the real trained model, webhook signature
> verification, app wiring) run with no external dependencies:
> `cd backend && pytest -m "unit or smoke"`. Integration tests that need a real database skip
> themselves with a clear message rather than silently pretending to pass — see
> [`backend/tests/conftest.py`](backend/tests/conftest.py). The full suite (120 test
> functions, 143 collected test cases including every integration test) has actually been run
> against a live PostgreSQL instance and passes — see [`docs/deployment.md`](docs/deployment.md)
> for local-Postgres setup notes and [`docs/reliability.md`](docs/reliability.md) for what
> each test proves.

For Docker Compose (full local stack: Postgres + backend + frontend in one command) and
deploying to Render, see [`docs/deployment.md`](docs/deployment.md) — includes a
ready-to-use `render.yaml` blueprint.

## Razorpay integration

RecoveryOS is honest about what Razorpay's API can and can't do — most importantly, **there is
no API to force-retry a failed one-time payment**; real recovery works through generating a
new Payment Link, always created with `accept_partial: false` so it can only ever be settled
in full. Every claim in this repo about "real Razorpay integration" vs "simulated" is
enumerated in [`docs/razorpay-integration.md`](docs/razorpay-integration.md), sourced from the
live Razorpay documentation, not assumed. Every adapter is implemented against the verified
real API shape and covered by tests against a mocked HTTP layer, including retry, timeout,
429, and 5xx behavior. With `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` configured, the adapter
calls the live Razorpay API directly; without them, it falls back to a clearly-labeled
simulator implementing the same interface, so the rest of the pipeline runs identically
either way.

## Benchmark results

Reproducible: `python simulator/benchmark/baseline_runner.py` (fixed `seed=42`, ~11s against
the full 7,500-row held-out test set). Money figures in ₹ Lakh (1L = ₹100,000):

| Baseline | Recovered revenue | Net Recovery Value | Recovery rate | Precision | Unnecessary action rate | Policy rejection rate |
|---|---|---|---|---|---|---|
| Rules (`ALWAYS_RETRY`) | ₹36.94L | ₹36.93L | 21.7% | 0.217 | 78.3% | 0% |
| Rules (`STATIC_RULES`) | ₹52.54L | ₹52.53L | 30.4% | 0.312 | 68.8% | 0% |
| ML (`ML_ONLY`) | **₹53.62L** | **₹95.17L** | **31.3%** | 0.313 | 68.7% | 0% |
| Full RecoveryOS (`RECOVERYOS_FULL` = ML + Policy) | ₹47.96L | ₹81.89L | 28.2% | **0.335** | **66.5%** | 15.9% |

RecoveryOS does not lead on raw recovered revenue or Net Recovery Value — ML_ONLY's NRV is
inflated by a less-calibrated probability estimate that overstates *expected* recovery
relative to what it actually realizes (see the calibration discussion in
`docs/ml-evaluation.md`). RecoveryOS wins on **discipline**: it intervenes on far fewer cases,
more precisely, and its 15.9% policy-rejection rate reflects cases where it correctly declined
to act rather than chase a low-expected-value retry. The full breakdown, including the
AI-inclusive 5th arm, is in [`docs/ml-evaluation.md`](docs/ml-evaluation.md) and
[`docs/ai-ablation.md`](docs/ai-ablation.md).

## Five-minute demo flow

Full script with exact UI steps: [`docs/demo-script.md`](docs/demo-script.md). Condensed:

1. **Command Center** (`/`) — live Revenue at Risk / Actual Recovered Revenue / Recovery Rate,
   starting at honest zeros.
2. **Generate a failure storm** (`/simulation`) — real, signed webhook POSTs through the same
   endpoint real Razorpay traffic hits; watch the numbers move as the background worker
   processes them.
3. **Open a case's Decision Trace** — real ML score, AI diagnosis (or an honest "no valid AI
   diagnosis" if no key is configured), optimizer ranking, and policy approval.
4. **Execute a recovery action** — a real (or simulator-backed) Payment Link gets created;
   simulate the customer paying it via a `payment_link.paid` webhook.
5. **Watch reconciliation close the loop** — the case resolves to `SUCCEEDED`, "Actual
   Recovered Revenue" on the Command Center moves by exactly that amount, and the Audit Ledger
   shows the full, traceable chain from detection to recovery.
6. **Benchmark page** (`/benchmark`) — the honest 4-baseline comparison above.
7. **A blocked bad decision** — a case where the optimizer's top pick is retried past its
   attempt budget; the Decision Trace shows the policy engine refusing it, not silently acting.

## Documentation index

| Doc | Contents |
|---|---|
| [`docs/deployment.md`](docs/deployment.md) | Local (native + Docker Compose) and Render deployment, step by step |
| [`docs/architecture.md`](docs/architecture.md) | Components, data flow, AI/ML/policy/execution boundaries, failure handling, scaling path |
| [`docs/track-alignment.md`](docs/track-alignment.md) | Every Track 03 requirement → component → implementation → test → demo evidence |
| [`docs/razorpay-integration.md`](docs/razorpay-integration.md) | What's real vs simulated, sourced from verified Razorpay docs |
| [`docs/decisions.md`](docs/decisions.md) | ADRs — why FastAPI/Postgres/no-Redis/no-microservices/etc. |
| [`docs/ai-design.md`](docs/ai-design.md) | LLM role, prompt architecture, validation, failure handling |
| [`docs/ml-evaluation.md`](docs/ml-evaluation.md) | Dataset, features, leakage prevention, real trained-model metrics, real 4-baseline benchmark results |
| [`docs/ai-ablation.md`](docs/ai-ablation.md) | The 5th, AI-inclusive benchmark arm — setup, metrics, honest results |
| [`docs/reliability.md`](docs/reliability.md) | Every safety invariant with its enforcement mechanism and the test proving it |
| [`docs/security.md`](docs/security.md) | Webhook security, secrets, prompt-injection defense |
| [`docs/limitations.md`](docs/limitations.md) | What's synthetic, simulated, or out of scope — stated plainly |
| [`docs/interview-defense.md`](docs/interview-defense.md) | Answers to the hard questions a reviewer would actually ask |
| [`docs/final-readiness-report.md`](docs/final-readiness-report.md) | Readiness summary — what's real, safety guarantees, test/benchmark commands |
| [`docs/demo-script.md`](docs/demo-script.md) | 5-minute live demo script |

## License

Buildathon submission — no license granted for reuse.
