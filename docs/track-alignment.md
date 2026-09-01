# Track 03 Alignment — AI Revenue Recovery

Every requirement below is quoted or paraphrased from the live buildathon page (verified
Phase 0 — see `docs/razorpay-integration.md` §1). The **Status** column is honest: it
distinguishes "real and tested," "real but needs a live database/credentials to exercise,"
and "out of scope" — never implying more than what's actually built.

## Core requirement mapping

| Track 03 requirement | Architecture component | Implementation | Test | Status |
|---|---|---|---|---|
| **Detect revenue at risk** | Revenue Signal Engine | `app/services/revenue_signal_service.py`'s `revenue_at_risk()` (pure predicate) + `detect_opportunity()` | `tests/unit/test_payment_state_machine.py` (reconstruction), DB-gated integration coverage for the opportunity write path | **Real.** Wired into `pipeline_orchestrator.process_failed_payment()`, runs automatically off every `payment.failed` webhook (real or simulated). |
| **Determine the right intervention** | ML Predictor (real trained LightGBM model) + AI Diagnostician (real Anthropic integration) + Intervention Optimizer | `app/agents/ml_predictor.py`, `app/agents/ai_diagnostician.py`, `app/services/analysis_service.py`, `app/services/optimizer_service.py` | `tests/unit/test_ml_predictor.py` (against the real trained artifact), `tests/unit/test_ai_diagnostician.py` (12 tests), `tests/unit/test_optimizer.py` | **Real.** Model trained and benchmarked (docs/ml-evaluation.md); AI diagnosis works with a real Anthropic key configured, degrades to ML-only signal without one — the pipeline is fully functional either way. |
| **Bounded recovery execution** | Policy Gate + Executor | `app/policies/policy_engine.py` (8 real rules), `app/executors/action_executor.py`, `app/services/execution_service.py`, the 7-value `ActionType` allowlist | `tests/unit/test_policy_engine.py` (11 tests incl. the bad-AI-demo scenario), `tests/unit/test_action_executor.py` (unknown-action/consent guards) | **Real**, including the SMART_RETRY/DELAYED_RETRY/CUSTOMER_ACTION_REQUEST → real Payment Link (or simulator) mechanism per docs/razorpay-integration.md. |
| **Measured money recovered across a batch** | Benchmark Engine | `simulator/benchmark/baseline_runner.py` — 4 baselines against the real trained model + real policy engine + real optimizer, over the full 7,500-row held-out test set | Run: `python simulator/benchmark/baseline_runner.py` (~11s, reproducible) | **Real, executed, results in docs/ml-evaluation.md** — including the honest finding that RecoveryOS does not win on raw recovered revenue, only on precision/efficiency. |
| **Compliant escalation** | `ESCALATION` action + consent tracking | `app/executors/handlers/escalation_handler.py`, `recovery_actions.consent_recorded`, 3-layer consent enforcement (policy rule + state machine guard + executor precondition) | `test_hinglish_voice_execution_blocked_without_consent`, `test_hinglish_voice_refuses_to_dispatch_without_recorded_consent` | **Real**, all 3 layers independently tested. |
| **Stopping rules** | Retry-limit + recovery-window policy rules | `recovery_cases.max_attempts`/`attempt_count`, `policies/rules.py::check_retry_limit_reached`/`check_recovery_window_expired` | `test_failed_expires_once_attempt_budget_exhausted`, `test_rejects_recovery_window_expired`, `test_bad_ai_demo_scenario_max_retries_blocks_smart_retry` | **Real.** |
| **Audit trail** | Recovery Ledger | `audit_logs` table, `app/services/ledger_service.py` (the one call site), populated at every pipeline hop | `tests/unit/test_audit_log_immutability.py` | **Real** — schema, immutability guarantee, and population are all live; `GET /api/audit` and the Audit Ledger frontend page read it. |

## What genuinely needs infrastructure this environment doesn't have

The decision-making code above is fully real and unit-tested with zero external dependencies.
What's real-but-unverified-**in this specific development environment** (no Docker/Postgres
available here — see README):

- The full DB-backed pipeline run (webhook → ingestion → worker → case → ledger, end to end)
  — written, type-checked, and covered by integration tests that self-skip without a live
  database rather than being faked as passing.
- Real Razorpay test-mode API calls (the adapters are real and tested against a mocked HTTP
  layer with `respx`, including retry/no-retry behavior; a live call needs real Razorpay test
  credentials, which weren't available in this environment either).
- The Docker Compose deployment (`docker-compose.yml`, `backend/Dockerfile` are written
  correctly but unexercised — no Docker available here).

## Example directions — what's in scope vs deferred

The track lists 7 example directions. RecoveryOS's first-class, fully-wired workflow is
**failed one-time payment → recovery**:

| Direction | In this build? |
|---|---|
| Payment degradation → root cause → recovery action | **Yes — first-class, fully wired end to end.** |
| Hinglish voice recovery | **Yes — signature feature, fully wired.** Selected by the same optimizer/policy decision engine as every other action (see docs/razorpay-integration.md §7), consent-gated 3 independent ways. |
| Failed-subscription recovery | **Partial.** The real Razorpay levers exist and are tested (`app/integrations/subscription_adapter.py` — `subscription_card_change`, invoice charging) and the domain model has `OpportunityType.SUBSCRIPTION_PENDING`/`HALTED`. **Not wired**: `revenue_signal_service.py` and `razorpay_payload_parser.py` only detect/parse one-time `payment.*` events, not `subscription.*` events — so a subscription going halted does not yet automatically create an opportunity. Honestly scoped as a real but incomplete extension, not claimed as done. |
| Checkout drop-off recovery | Not in scope. Razorpay's webhook surface doesn't expose pre-payment checkout abandonment the way it exposes payment failures; doing this honestly needs client-side instrumentation this build doesn't have. |
| B2B receivables chaser | Not in scope — no invoicing/receivables data model. |
| Mandate retry sequencer | Not in scope beyond what subscription auto-retry (Razorpay-managed) already covers. |
| Promise-to-pay tracker | Not in scope — a natural future extension of `CUSTOMER_ACTION_REQUEST` + `consent_recorded`. |

## The judging bar, restated as a checklist

> "Don't just identify the problem. Show measured money recovered across a batch, with
> compliant escalation, stopping rules, and an audit trail."

- [x] **Measured money recovered across a batch** — `simulator/benchmark/baseline_runner.py`, executed against 7,500 real held-out rows, results in docs/ml-evaluation.md.
- [x] **Stopping rules exist as a real mechanism** — attempt-budget expiry, unit-tested.
- [x] **Compliant escalation has a real, 3-layer consent gate**.
- [x] **Audit trail is schema-immutable and populated at every pipeline hop**.
- [x] **A live end-to-end demo path exists** — docs/demo-script.md, runnable once Docker/Postgres and (optionally) real credentials are available; not independently re-verified against a live database in this development environment (see above).
