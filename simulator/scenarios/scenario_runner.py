"""Builds the event sequence for each named failure-injection scenario
(scenario_definitions.py). Returns `(payload, forced_event_id)` pairs — `forced_event_id` is
`None` unless the scenario specifically needs control over the `x-razorpay-event-id` (e.g.
sending the exact same id twice to prove idempotency). Pure data generation only; posting the
events through the real webhook endpoint is `backend/app/services/simulator_service.py`'s job
(ADR-004), invoked by `backend/app/api/simulator.py`.
"""

import uuid

from simulator.generators.event_generator import (
    build_payment_captured_event,
    build_payment_failed_event,
    new_simulated_payment,
)

EventBatch = list[tuple[dict, str | None]]


def bank_failure() -> EventBatch:
    payment = new_simulated_payment(amount=849_900, method="upi")
    event = build_payment_failed_event(
        payment=payment,
        error_code="GATEWAY_ERROR",
        error_description="Bank declined the transaction",
        error_source="bank",
        error_reason="issuer_declined",
    )
    return [(event, None)]


def api_timeout() -> EventBatch:
    # Represents a payment failing due to a gateway timeout — the real "API timeout" this
    # scenario demonstrates is exercised at the Razorpay-adapter layer (bounded retry, see
    # app/integrations/razorpay_client.py), not at ingestion; this generates the failure that
    # would trigger a SMART_RETRY attempt where that retry logic is what's under test.
    payment = new_simulated_payment(amount=249_900, method="card")
    event = build_payment_failed_event(
        payment=payment,
        error_code="GATEWAY_ERROR",
        error_description="Gateway timed out",
        error_source="gateway",
        error_reason="gateway_timeout",
    )
    return [(event, None)]


def duplicate_webhook() -> EventBatch:
    payment = new_simulated_payment(amount=99_900, method="upi")
    event = build_payment_failed_event(payment=payment, error_reason="insufficient_funds")
    forced_id = f"evt_sim_dup_{uuid.uuid4().hex}"
    return [(event, forced_id), (event, forced_id)]  # same id, delivered twice


def out_of_order_webhook() -> EventBatch:
    payment = new_simulated_payment(amount=149_900, method="upi")
    failed = build_payment_failed_event(payment=payment, error_reason="insufficient_funds")
    captured = build_payment_captured_event(payment=payment)
    # Deliver the newer event first, then the older one — the older one must be rejected as
    # stale by the (created_at, sequence_id) watermark guard, not corrupt the CAPTURED state.
    captured["created_at"] = failed["created_at"] + 100
    return [(captured, None), (failed, None)]


def already_recovered_payment() -> EventBatch:
    payment = new_simulated_payment(amount=349_900, method="netbanking")
    failed = build_payment_failed_event(payment=payment, error_reason="insufficient_funds")
    captured = build_payment_captured_event(payment=payment)
    captured["created_at"] = failed["created_at"] + 5
    return [(failed, None), (captured, None)]


SCENARIO_RUNNERS = {
    "bank_failure": bank_failure,
    "api_timeout": api_timeout,
    "duplicate_webhook": duplicate_webhook,
    "out_of_order_webhook": out_of_order_webhook,
    "already_recovered_payment": already_recovered_payment,
}
