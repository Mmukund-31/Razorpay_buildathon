# RecoveryOS — Architecture

## Core principle

```
Signals → Prediction → AI diagnosis → Optimization → Policy → Execution → Outcome → Audit
```

Restated as a hard rule: **the LLM never touches money.** It classifies and proposes through
a strict, Pydantic-validated JSON contract with zero tool/function-calling access. A
deterministic policy engine is the only thing that can approve a financial action. A single
executor module is the only code allowed to call Razorpay or a customer-communication
provider. This document describes the components that implement that rule and what happens
when each one fails.

## Data flow

```
Razorpay Test Mode --webhook--> Ingestion (verify sig, dedupe on event_id, persist, ack 2xx)
   --> webhook_events(PENDING) --[async DB-polling worker]-->
   State Reconstruction (guarded payment state transition, ordering-safe)
   --> Revenue Signal Engine --> recovery_opportunities
   --> Recovery Opportunity Engine --> recovery_cases (DETECTED -> ELIGIBLE)
   --> ANALYZING: ML Predictor ‖ AI Diagnostician (parallel, both -> agent_decisions)
   --> Intervention Optimizer --> ACTION_PROPOSED (candidates + expected values)
   --> Policy Gate --> POLICY_APPROVED | POLICY_REJECTED (policy_evaluations)
   --> Executor --> Razorpay adapter | CommunicationProvider --> recovery_actions
   --> Outcome Engine (webhook/poll reconciliation) --> SUCCEEDED | FAILED
   --> Recovery Ledger (audit_logs, every hop)
   --> Benchmark Engine (offline, reads experiment_results)
```

## Components and responsibilities

| Component | Responsibility | Code |
|---|---|---|
| Event Ingestion | Verify HMAC-SHA256 signature over the **raw** body, dedupe on `x-razorpay-event-id`, persist, ack <5s | `backend/app/api/webhooks.py`, `backend/app/integrations/webhook_verifier.py` |
| Background Worker | DB-polling async loop; drives everything past persistence | `backend/app/core/background_worker.py` |
| State Reconstruction | Applies the payment state machine with ordering guards | `backend/app/domain/payment_state_machine.py`, `backend/app/services/state_reconstruction_service.py` |
| Revenue Signal Engine | Decides whether a reconstructed state is revenue at risk | `backend/app/services/revenue_signal_service.py` |
| Recovery Opportunity Engine | Opportunity → case conversion, eligibility gating | `backend/app/services/recovery_case_service.py` |
| ML Predictor | `P(success \| context, action)` per candidate action | `backend/app/agents/ml_predictor.py` → `ml/inference/` |
| AI Diagnostician | Structured, validated diagnosis JSON, zero tools | `backend/app/agents/ai_diagnostician.py` |
| Intervention Optimizer | `expected_value = probability × amount − intervention_cost − risk_cost`, ranks candidates | `backend/app/services/optimizer_service.py` |
| Policy Gate | Deterministic allow/deny with reason codes | `backend/app/policies/policy_engine.py` |
| Executor | The only module allowed to call Razorpay or a communication provider | `backend/app/executors/action_executor.py` |
| Outcome Engine | Reconciles later signals back onto the case | `backend/app/services/outcome_service.py` |
| Recovery Ledger | Append-only audit trail | `backend/app/repositories/audit_log_repository.py` |
| Benchmark Engine | Offline 4-baseline comparison against synthetic data | `simulator/benchmark/`, `ml/evaluation/` |

## The three boundary lines

These are enforced in code and schema, not just documented:

1. **AI/ML → Optimizer.** The LLM has zero tool/function bindings — it cannot invoke any
   adapter, repository, or executor code path. It only ever writes
   `agent_decisions.raw_output` / `validated_output`. The optimizer reads only rows where
   `is_valid=true`; a row with `is_valid=false` is "no signal," never a fallback command.
2. **Optimizer → Policy → Execution.** The optimizer can reach `ACTION_PROPOSED`, never
   `POLICY_APPROVED`. Every `recovery_actions` row has a **mandatory NOT NULL FK** to the
   approving `policy_evaluations.id` — there is no code path in `ActionExecutor` that
   constructs an action row without one, and the executor re-reads case status from the
   database immediately before acting, never a cached value.
3. **Execution.** `ActionExecutor.execute()` dispatches strictly on the 7-value `ActionType`
   enum, Pydantic-validated before dispatch, mirrored by a DB `CHECK` constraint as an
   independent second layer. The executor never reads or sets `amount` — it always comes
   from `payments.amount`, immutable at execution time. Only the executor may import the
   Razorpay adapters or `CommunicationProvider` implementations.

## Payment and recovery-case state machines

See `backend/app/domain/payment_state_machine.py` and
`backend/app/domain/recovery_case_state_machine.py` for the full transition tables and their
docstrings — both are pure, in-memory, unit-tested logic with zero I/O.

**Payment**: `CREATED → AUTHORIZED → CAPTURED` (terminal), with `FAILED` reachable from
`CREATED`/`AUTHORIZED`, and — a verified Razorpay quirk — `FAILED → CAPTURED` also legal (a
UPI customer corrects a wrong PIN and succeeds on the same `payment_id`). `CAPTURED →
REFUNDED` (terminal). An unrecognized event on a non-terminal state degrades to `UNKNOWN`
rather than being rejected. Every transition is guarded by `is_terminal` and an ordering
watermark `(last_event_created_at, last_event_sequence_id)`, since Razorpay does not
guarantee webhook delivery order.

**Recovery case** (13 states): `DETECTED → ELIGIBLE → ANALYZING → ACTION_PROPOSED →
POLICY_APPROVED → (SCHEDULED →) EXECUTING`, with `ABSTAINED`, `POLICY_REJECTED`, `EXPIRED`,
`ESCALATED`, `SUCCEEDED` as terminal outcomes, and `FAILED` looping back to `ELIGIBLE` only
while `attempt_count < max_attempts`. A cross-cutting guard checked at the top of every
transition — `payment_captured`, always freshly read, never cached — force-jumps the case
straight to `SUCCEEDED` regardless of its current state. That single guard is the concrete
enforcement of "a recovered payment can't be retried," and it is also how `EXECUTING`
actually resolves for the 5 real recovery-attempt actions (SMART_RETRY, DELAYED_RETRY,
CUSTOMER_NOTIFICATION, CUSTOMER_ACTION_REQUEST, HINGLISH_VOICE): a successfully-dispatched
Payment Link isn't the same moment as the customer paying it, so dispatch success alone
deliberately does **not** move those 5 actions to `SUCCEEDED` — the case stays `EXECUTING`
until a later `payment.captured` webhook resolves it via this same guard
(`app/services/pipeline_orchestrator.py::_resolve_if_captured`). `ESCALATION` and `NO_ACTION`
are the two exceptions where dispatching **is** the whole outcome, so they resolve immediately
via their own dedicated triggers (`ESCALATION_COMPLETE` → `ESCALATED`, `NO_ACTION_COMPLETE` →
`ABSTAINED`).

## Failure handling per external dependency

| Dependency | Failure mode | Behavior |
|---|---|---|
| Razorpay adapter | Timeout / 5xx | Bounded retry (3×, exponential backoff) at the adapter layer only, then `recovery_actions.status=FAILED` — no silent re-evaluation |
| LLM | Timeout / invalid JSON | Recorded as `agent_decisions.is_valid=false`, not a crash. If both ML and AI produce no signal, the case goes to `ABSTAINED` — a first-class terminal state, not an error. A cooldown-window circuit breaker skips AI diagnosis after N consecutive failures, falling back to ML+policy only |
| Database | Unreachable | `/api/health` reports `degraded`, never crashes. Webhook ingestion returns 5xx if it can't persist — intentional: Razorpay's own 24h retry means we never fake an ack to avoid losing an event |
| Background worker | Crash mid-batch | Durability lives in `webhook_events.processing_status`, not in-memory queue state — a restarted worker just re-polls `PENDING` rows |

## Why no Redis (ADR-002, see decisions.md)

A single in-process asyncio worker polls `webhook_events` for `PENDING` rows ordered by
`(razorpay_created_at, sequence_id)`. This is crash-recoverable via DB status columns, not a
fragile in-memory queue, and needs no extra infrastructure for a single-instance buildathon
deployment. The worker's interface (`app/core/background_worker.py`) is isolated enough that
swapping in Redis + RQ/Celery later is a drop-in replacement, not a rewrite.

## Scaling path (documented, not built)

Single-instance today. The production path: swap the DB-polling worker for Redis-backed
workers behind the same interface; add read replicas for `/api/dashboard` and
`/api/analytics/benchmark`; partition `recovery_cases`/`audit_logs` by `created_at` at high
volume; move the LLM/ML calls to a dedicated inference service if latency under load demands
it. None of this is implemented — it's a conscious deferral, not an omission, because a
buildathon-scale deployment doesn't need it and building it now would just be complexity for
appearance's sake.

## Repository layout

```
backend/     FastAPI service — API, domain model, services, policies, executors, integrations
ml/          Synthetic data generation, feature engineering, training, evaluation
simulator/   Failure-storm / scenario generators and the 4-baseline benchmark runner
frontend/    React + TypeScript operations dashboard
docs/        This document and its siblings
scripts/     Operational scripts (migrations, seeding, dataset generation, simulator runs)
```

See `docs/decisions.md` for the reasoning behind each major technology and architecture
choice, and `docs/track-alignment.md` for how every piece above maps to a specific Track 03
requirement.
