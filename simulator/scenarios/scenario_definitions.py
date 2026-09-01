"""Named failure-injection scenarios (docs/architecture.md / product spec section 29). Every
scenario must drive events through the SAME ingestion/pipeline code real Razorpay webhooks
use — never a separate fake path (docs/decisions.md ADR-004) — so what the demo shows is
what the production code path actually does under that condition.

5 of the 8 scenarios below have a generator function wired into
`simulator/scenarios/scenario_runner.py::SCENARIO_RUNNERS`, reachable via
`POST /api/simulator/scenario` and the Simulation page's Failure Injection panel:
`bank_failure`, `api_timeout`, `duplicate_webhook`, `out_of_order_webhook`,
`already_recovered_payment` — each is a real webhook-shaped event (or sequence of them).

The remaining 3 — `malformed_ai_response`, `low_confidence_ml_prediction`,
`database_unavailable` — are deliberately NOT wired the same way. Each tests an internal
component's failure mode, not a webhook payload shape: forcing them into this module's "pure
data generation" contract would mean reaching into internal state (mocking the LLM response,
forcing an ML score, severing the DB) from what's supposed to be a webhook-shape generator —
exactly the "parallel fake path" ADR-004 rules out. They are proven instead by dedicated
tests that exercise the real code directly:

- `malformed_ai_response` → `backend/tests/unit/test_ai_diagnostician.py`
  (`test_malformed_json_is_rejected` and siblings) — a response that fails
  `AIDiagnosisOutput` validation is recorded `is_valid=False` and never reaches the optimizer.
- `low_confidence_ml_prediction` → `backend/tests/unit/test_policy_engine.py`
  (`test_rejects_confidence_below_min`) — the policy engine rejects with
  `CONFIDENCE_BELOW_MIN` before a case can reach `POLICY_APPROVED`.
- `database_unavailable` → `backend/tests/integration/test_database_unavailable.py` — webhook
  ingestion returns a real 5xx (via FastAPI's dependency-override mechanism simulating an
  unreachable DB), never a fake 200 ack, and persists nothing.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    name: str
    description: str
    expected_safe_behavior: str


SCENARIOS: tuple[ScenarioDefinition, ...] = (
    ScenarioDefinition(
        "bank_failure",
        "Simulated bank/issuer-side decline injected as a payment.failed webhook.",
        "Revenue signal detected, opportunity created, normal recovery flow proceeds.",
    ),
    ScenarioDefinition(
        "api_timeout",
        "Razorpay adapter call (Payment Link creation) times out mid-execution.",
        "Adapter retries (bounded, exponential backoff) then marks the action FAILED — no "
        "silent re-evaluation, no duplicate action on retry.",
    ),
    ScenarioDefinition(
        "duplicate_webhook",
        "The same razorpay_event_id delivered twice.",
        "Second delivery hits the UNIQUE constraint, acked 200, never reprocessed.",
    ),
    ScenarioDefinition(
        "out_of_order_webhook",
        "An older event delivered after a newer one was already applied.",
        "Rejected by the (created_at, sequence_id) watermark guard, logged as "
        "EVENT_IGNORED_STALE, current state untouched.",
    ),
    ScenarioDefinition(
        "already_recovered_payment",
        "A recovery action is attempted against a payment that independently got captured.",
        "The payment_captured guard force-transitions the case to SUCCEEDED; the action is "
        "never (re)executed.",
    ),
    ScenarioDefinition(
        "malformed_ai_response",
        "The AI Diagnostician returns JSON that fails AIDiagnosisOutput validation.",
        "agent_decisions.is_valid=false; optimizer treats it as no signal, never a fallback "
        "instruction.",
    ),
    ScenarioDefinition(
        "low_confidence_ml_prediction",
        "ML predictor returns a probability with confidence below MIN_CONFIDENCE.",
        "Policy rejects with confidence_below_min; case does not reach POLICY_APPROVED.",
    ),
    ScenarioDefinition(
        "database_unavailable",
        "The database is unreachable during ingestion or execution.",
        "Webhook ingestion returns 5xx (never a fake ack); no money-moving action is executed "
        "without a durable, committed policy_evaluations row.",
    ),
)
