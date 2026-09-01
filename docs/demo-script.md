# Demo Script (5 minutes)

Prerequisites: `docker compose up -d postgres && cd backend && alembic upgrade head`, a
trained model (`python ml/training/train_lightgbm.py` after generating a dataset — see
README), backend running (`uvicorn app.main:app --reload`), frontend running (`npm run dev` in
`frontend/`). `LLM_API_KEY` and Razorpay test-mode credentials are optional — the system runs
fully autonomously without them (LLM falls back to ML-only scoring; Razorpay falls back to the
simulator gateway, see docs/razorpay-integration.md §8).

**0:00 — Problem.** "Revenue is lost through failed payments, and most systems just log it.
RecoveryOS closes the loop: detect, diagnose, decide, act, and prove it — with hard financial
safety limits the AI cannot cross."

**0:20 — Command Center** (`/`). Show the live metrics — Revenue at Risk, Recoverable
Revenue, Recovered Revenue, Recovery Rate, Active Cases, Actions Executed/Prevented,
Abstentions — all real aggregate queries (`app/services/dashboard_service.py`), starting at
honest zeros on a fresh database.

**0:45 — Failure storm.** Simulation page (`/simulation`) → "Generate Failure Storm (100
events)". Each event is a real, signed webhook POST through `POST /api/webhooks/razorpay` —
the exact endpoint real Razorpay test-mode traffic hits (`app/services/simulator_service.py`).
Refresh the Command Center a few seconds later — the numbers move because the background
worker actually processed them through the full pipeline.

**1:15 — Recovery Queue** (`/queue`). Filter by status; show cases moving through
DETECTED → ELIGIBLE → ANALYZING → ACTION_PROPOSED → POLICY_APPROVED → EXECUTING.

**1:40 — Open a high-value case.** Click into one from the queue (`/cases/{id}`).

**2:00 — Decision Trace** (`/cases/{id}/trace`). Walk through all 5 sections live: why the
payment failed (real `failure_class`/`error_reason`), what the AI diagnosed (or, honestly, "no
LLM key configured — the pipeline fell back to the ML score alone," if that's the live state —
never hidden), every candidate action with its real ML-predicted probability and
optimizer-computed expected value, which one won and why, and the policy decision with its
`policy_version` and reason codes.

**2:40 — Hinglish voice recovery.** Open (or create, via the Simulation scenarios) a case
whose selected action is `HINGLISH_VOICE`. On the case page, check "Customer consented" and
click Evaluate/Execute — this exercises the real consent-then-policy-then-execute flow
(`app/executors/handlers/hinglish_voice_handler.py`), producing a real (simulated, clearly
logged as such) transcript ending in a Hinglish affirmative response.

**3:10 — Successful recovery.** Show a case that reached `SUCCEEDED` and its ledger entries
(`PAYMENT_RECOVERED`).

**3:30 — Bad-AI demo.** Simulation page → run a scenario (or manually push a case's
`attempt_count` to its `max_attempts` via repeated failure events) so the optimizer's top
candidate is `SMART_RETRY` but the retry limit is already exhausted.

**3:50 — Policy blocks it.** Open that case's Decision Trace: `policy_decision.allowed=false`,
`reason_codes: ["retry_limit_reached"]` — a real `PolicyEngine.evaluate()` call
(`tests/unit/test_policy_engine.py::test_bad_ai_demo_scenario_max_retries_blocks_smart_retry`
proves this exact scenario), not a scripted screenshot.

**4:10 — Benchmark** (`/benchmark`). Run
`python simulator/benchmark/baseline_runner.py` beforehand (or during setup — it takes ~11
seconds against the full 7,500-row held-out test set). Show the 4-baseline comparison — and
say the honest thing: RecoveryOS doesn't win on raw recovered revenue here, it wins on
precision, unnecessary-action rate, and revenue per intervention. See docs/ml-evaluation.md
for the full, real numbers and the reasoning.

**4:30 — Audit Ledger** (`/audit`). Show the immutable trail for the cases just demonstrated —
every hop, one `correlation_id` per case, no update/delete path exists in the code.

**4:45 — Architecture.** One slide: `Signals → Prediction → AI diagnosis → Optimization →
Policy → Execution → Outcome → Audit`. "The LLM proposes. It never executes. A deterministic
policy engine is the only thing that approves a financial action."

**5:00 — Closing.** "RecoveryOS doesn't just predict which payments might recover. It closes
the loop from revenue-risk detection to safe, explainable and measurable recovery."
