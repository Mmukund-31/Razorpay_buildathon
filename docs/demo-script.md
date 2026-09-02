# Demo Script (5 minutes)

Prerequisites: a reachable, migrated Postgres (`alembic upgrade head` — Docker Compose or a
native install, see README Quickstart), a trained model
(`python ml/training/train_lightgbm.py` after generating a dataset), backend running
(`uvicorn app.main:app --reload`), frontend running (`npm run dev` in `frontend/`).
`LLM_API_KEY` and Razorpay test-mode credentials are optional — the system runs fully
autonomously without them (LLM falls back to ML-only scoring; Razorpay falls back to the
clearly-labeled simulator gateway, see `docs/razorpay-integration.md` §8). If real Razorpay
Test Mode credentials ARE configured, this script's 3:00 beat becomes a genuine live payment;
otherwise it stays in simulator mode, said out loud rather than implied.

**0:00 — Problem.** "Revenue is lost through failed payments, and most systems just log it.
RecoveryOS closes the loop: detect, diagnose, decide, act — and now, provably, reconcile the
outcome and prove the money actually came back."

**0:20 — Command Center** (`/`). Live metrics — Revenue at Risk, Recoverable Revenue,
**Actual** Recovered Revenue, Recovery Rate, Active Cases, Actions Executed/Prevented,
Abstentions — all real aggregate queries (`app/services/dashboard_service.py`), starting at
honest zeros on a fresh database. Point out that "Recovered Revenue" is the *actual*
reconciled amount (`RecoveryCase.actual_recovered_amount`), not the original at-risk estimate.

**0:45 — Generate Failure Storm.** Simulation page (`/simulation`) → "Generate Failure Storm."
Each event is a real, signed webhook POST through `POST /api/webhooks/razorpay` — the exact
endpoint real Razorpay test-mode traffic hits (`app/services/simulator_service.py`), or run
`python scripts/run_simulator.py failure-storm --count 100` from a terminal for the same
effect with visible JSON output. Refresh the Command Center — the numbers move because the
background worker actually processed them through the full pipeline.

**1:15 — Open a high-value recovery case.** Recovery Queue (`/queue`) → pick one, open its
Decision Trace (`/cases/{id}/trace`).

**1:35 — ML score.** Section 3 ("What actions were considered") — every candidate action's
real ML-predicted `P(recovery)` from the trained LightGBM model, not a canned number.

**1:50 — AI diagnosis.** Section 2 — the AI's stated `failure_class`, free-text diagnosis, and
confidence (or, honestly, "no valid AI diagnosis — no LLM key configured, the pipeline fell
back to the ML score alone," if that's the live state — never hidden, see
`docs/reliability.md`'s abstention rule).

**2:05 — Candidate action optimization.** Same table — every candidate's `expected_recovery`,
`intervention_cost`, `risk_cost`, and the resulting `expected_value` ranking; the AI's nudge
(≤12%, only when its recommendation agrees with a valid ML score) is visible in which
candidate ends up on top.

**2:20 — Policy approval.** Section 4 — `policy_decision.allowed=true`, its `policy_version`.
"A deterministic 8-rule engine, zero LLM involvement, is the only thing that can approve this."

**2:35 — Hinglish customer intervention.** Open (or create, via a Simulation scenario) a case
whose selected action is `HINGLISH_VOICE`. Check "Customer consented" and Evaluate/Execute —
the real consent → policy → executor → audit flow
(`app/executors/handlers/hinglish_voice_handler.py`), producing a (clearly-labeled simulated)
transcript ending in a Hinglish affirmative response.

**3:00 — Razorpay Test Mode recovery, if available.** With real test-mode credentials
configured, execute a `SMART_RETRY` on a case and show the real Payment Link Razorpay
returned (`short_url`) — open it, pay with a test card/UPI ID
(`success@razorpay`), and let Razorpay deliver the real webhook. Without credentials, say so
plainly and continue with the simulator gateway — the pipeline code path from here is
identical either way (`app/integrations/gateway_factory.py`).

**3:20 — Webhook.** Whichever path: a `payment_link.paid` (or `payment.captured`) webhook
arrives at the same real `POST /api/webhooks/razorpay` endpoint, signature-verified,
persisted, and picked up by the background worker.

**3:35 — Outcome reconciliation.** The key beat of the whole flow:
`app/services/outcome_service.py::reconcile_outcome()` correlates the NEW payment (a
different `razorpay_payment_id` than the original failed one) back to this exact case via the
Payment Link's `reference_id`, verifies it's still eligible, and writes
`actual_recovered_amount` — idempotently, proven by
`tests/integration/test_payment_link_correlation.py` replaying the same webhook and showing
the amount never doubles.

**3:50 — ₹ recovered.** Refresh the case — status `SUCCEEDED`, and the Decision Trace's new
"Actual recovered revenue" panel shows the real reconciled amount, distinct from the expected-
value estimate above it. Refresh the Command Center — "Recovered Revenue" moved by exactly
that amount.

**4:05 — Bad AI recommendation.** Simulation page → run a scenario (or manually push a case's
`attempt_count` to its `max_attempts` via repeated failure events) so the optimizer's top
candidate is `SMART_RETRY` but the retry limit is already exhausted.

**4:20 — Policy blocks the unsafe action.** Open that case's Decision Trace: the red "AI
recommendation blocked" panel — action, reason (`Retry Limit Reached`), and the potential
unnecessary intervention amount that was avoided. A real `PolicyEngine.evaluate()` call
(`tests/unit/test_policy_engine.py::test_bad_ai_demo_scenario_max_retries_blocks_smart_retry`
proves this exact scenario), not a scripted screenshot.

**4:35 — Benchmark** (`/benchmark`). Run `python simulator/benchmark/baseline_runner.py`
beforehand (~11 seconds against the full 7,500-row held-out test set). Show the 4-baseline
comparison and the honest framing: RecoveryOS doesn't win on raw recovered revenue, or even on
Net Recovery Value (that's a calibration artifact of a less-disciplined baseline, not real
superiority — see `docs/ml-evaluation.md`) — it wins on precision, unnecessary-action rate,
and revenue per intervention. Mention the 5th, AI-inclusive arm (`docs/ai-ablation.md`) and
its honest, disclosed status.

**4:50 — Architecture.** One slide: `Signals → Prediction → AI diagnosis → Optimization →
Policy → Execution → Outcome Reconciliation → Audit`. "AI proposes. Optimization prioritizes.
Policy decides. Executor acts. Ledger proves."

**5:00 — Closing.** "RecoveryOS doesn't just predict which payments might recover. It closes
the loop — from revenue-risk detection all the way to a reconciled, audited, actually
recovered rupee — safely, explainably, and measurably."
