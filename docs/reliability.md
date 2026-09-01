# Reliability

## Safety invariants — where each is enforced, and the test proving it

| Invariant | Enforcement | Proof |
|---|---|---|
| A payment cannot be recovered twice | Partial unique index `recovery_cases(payment_id) WHERE status NOT IN ('FAILED','EXPIRED','ABSTAINED')` (at most one live case per payment) + the `payment_captured` guard checked first in every state transition | `tests/unit/test_recovery_case_state_machine.py::test_payment_already_captured_forces_succeeded_from_any_non_terminal_state` (parametrized over 8 starting states) |
| An action cannot bypass policy | `recovery_actions.policy_evaluation_id` is a mandatory `NOT NULL` FK to an `allowed=true` `policy_evaluations` row — `execution_service.execute()` fetches that row first and refuses to act (logs an error, returns) if none exists | Schema constraint + `execution_service._latest_approved_policy_evaluation()`'s guard |
| A recovered payment cannot be retried | Same `payment_captured` guard, checked before evaluating any other trigger, on every single transition regardless of the case's current state | Same test as above, plus `test_payment_captured_guard_does_not_refire_once_already_succeeded` |
| Retry limits cannot be exceeded | `RETRY_CHECK` trigger is FAILED's only way back to ELIGIBLE, and it compares `attempt_count` to `max_attempts` — no other path leaves FAILED | `test_failed_retries_to_eligible_under_attempt_budget`, `test_failed_expires_once_attempt_budget_exhausted` |
| Unknown actions cannot execute | `ActionExecutor` dispatches via a dict keyed on the 7-value `ActionType` enum (raises `UnknownActionType` otherwise), mirrored by a DB `CHECK` constraint on `recovery_actions.action_type` | `tests/unit/test_action_executor.py::test_unknown_action_type_raises_instead_of_silently_executing` |
| Malformed AI output cannot reach the executor | `AIDiagnosisOutput` Pydantic validation (`extra="forbid"`); `is_valid=False` on any failure, and the optimizer only reads `agent_decisions.validated_output` where `is_valid=true` | `tests/unit/test_ai_diagnostician.py` (12 tests) |
| Customer opt-out cannot be overridden | `check_customer_opted_out` policy rule — unconditional rejection, checked before expected-value/confidence rules | `tests/unit/test_policy_engine.py::test_rejects_customer_opted_out` |
| Duplicate webhook cannot duplicate a business action | `webhook_events.razorpay_event_id` UNIQUE (ingestion-level) + `recovery_actions.idempotency_key` UNIQUE, `f"{case_id}:{action_type}:{attempt_count}"` (execution-level) — two independent layers | `tests/unit/test_idempotency.py`, `tests/integration/test_webhook_ingestion.py` (both DB-gated, self-skip without Postgres — see below) |
| Out-of-order event cannot corrupt current state | `payments.last_event_created_at`/`last_event_sequence_id` watermark, checked in a single conditional UPDATE — never a blind `.status = x` | `tests/unit/test_payment_state_machine.py::test_stale_event_rejected_even_though_target_would_otherwise_be_legal` |
| A consent-required action cannot dispatch without consent | Three independent layers: (1) `check_consent_required_but_missing` policy rule, (2) the state machine's `BEGIN_EXECUTION` + `CONSENT_REQUIRED` guard, (3) `hinglish_voice_handler.handle()`'s own hard precondition check (raises `ConsentNotRecorded`) | `test_hinglish_voice_execution_blocked_without_consent` (policy+state machine), `tests/unit/test_action_executor.py::test_hinglish_voice_refuses_to_dispatch_without_recorded_consent` (executor) |

## Failure handling per external dependency — implemented, not just documented

| Dependency | What actually happens |
|---|---|
| Razorpay API | `RazorpayClient._request()`: 3-attempt exponential backoff (0.5s, 1s, 2s, capped at 4s) on timeouts and 5xx/429 only — a 4xx is never retried (verified: `test_does_not_retry_on_4xx`, `test_retries_on_5xx_then_succeeds`). Exhausted retries raise `RazorpayAPIError`, caught by `execution_service._dispatch()`, which marks the action FAILED and drives the case through `EXECUTION_FAILED` → the normal retry-budget loop — never a silent re-evaluation. |
| LLM | See docs/ai-design.md's failure-handling section — no key, malformed output, network failure, and the circuit breaker are each independently implemented and tested. |
| ML model | `ml/inference/predictor.load_active_model()` returns `None` (not an exception) if no artifact exists; `app/agents/ml_predictor.predict()` returns `is_valid=False` in that case — the optimizer treats a missing model exactly like a missing LLM signal. Verified: `test_predict_with_missing_model_returns_invalid`. |
| Database | `GET /api/health` runs `SELECT 1` and reports `"degraded"` (never crashes) on failure. Webhook ingestion returns a 5xx if it can't persist the event — deliberately: Razorpay's own at-least-once delivery with 24h exponential-backoff retry means never faking a 200 to a request we didn't durably record. |
| Background worker crash | Durability lives in `webhook_events.processing_status` (`PENDING`/`PROCESSING`/`PROCESSED`/`FAILED`), not in-memory queue state — a restarted worker just re-polls `PENDING` rows. `poll_once()` claims rows with `SELECT ... FOR UPDATE SKIP LOCKED`, so multiple workers can safely run concurrently without double-processing the same row. |

## Why 6 of 83 tests self-skip in this environment

This development environment has neither Docker nor a local PostgreSQL installation (see the
Phase 1 report and README's Quickstart note). Tests that genuinely need a live database
(`tests/integration/test_db_connectivity.py`, `test_webhook_ingestion.py`,
`tests/unit/test_idempotency.py`, and the intentionally-`skip`'d `test_pipeline_smoke.py`)
self-skip with an actionable message — `docker compose up -d postgres && alembic upgrade
head` — rather than being faked as passing or silently deleted. Every other safety-invariant
test above runs with zero external dependencies and passes in this environment right now.

## Observability

Structured JSON logging (`app/core/logging.py`, `python-json-logger`) throughout; every log
call in the pipeline includes at least one of `webhook_event_id`, `payment_id`,
`recovery_case_id`, `action`, or `correlation_id` in `extra=`. Every ledger entry
(`audit_logs`) carries a `correlation_id` shared across every hop of one pipeline run — from
`state_reconstruction_service.apply()`'s first `EVENT_IGNORED_STALE`/`PAYMENT_FAILED` entry
through `ACTION_EXECUTED`/`PAYMENT_RECOVERED` — so a single case's full history is one query
away (`GET /api/audit?entity_type=recovery_case&entity_id=...`, or by `correlation_id`).

Latency is recorded per ML prediction (`MLPrediction.latency_ms`) and per AI call
(`AIDiagnosisResult.latency_ms`), persisted onto `agent_decisions.latency_ms` — visible in the
decision trace for every case.
