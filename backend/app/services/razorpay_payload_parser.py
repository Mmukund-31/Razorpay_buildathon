"""Extracts normalized fields from a Razorpay (or simulator-generated, per ADR-004) webhook
payload. Pure, no I/O — the verified real payload shape (docs/razorpay-integration.md §3) is:

    {"event": "payment.failed", "created_at": <unix ts>,
     "payload": {"payment": {"entity": {"id": "pay_...", "order_id": "order_...",
                                          "amount": 849900, "currency": "INR",
                                          "status": "failed", "method": "upi",
                                          "email": "...", "contact": "...",
                                          "error_code": "...", "error_description": "...",
                                          "error_source": "...", "error_step": "...",
                                          "error_reason": "...", "notes": {...}}}}}

Simulator-generated payloads (simulator/generators/event_generator.py) match this exact
shape so this parser — and everything downstream of it — cannot tell the difference, per
ADR-004 ("the simulator drives the real pipeline, never a parallel fake one").
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedPaymentEvent:
    razorpay_payment_id: str
    razorpay_order_id: str | None
    amount: int
    currency: str
    method: str | None
    email: str | None
    contact: str | None
    customer_name: str | None
    error_code: str | None
    error_description: str | None
    error_source: str | None
    error_step: str | None
    error_reason: str | None


def parse_payment_entity(payload: dict) -> ParsedPaymentEvent | None:
    """Returns None if `payload` doesn't carry a payment entity at all (e.g. a
    subscription.* or payment.downtime.* event) — the caller should treat that as
    "nothing to reconstruct here" rather than an error.
    """
    entity = payload.get("payload", {}).get("payment", {}).get("entity")
    if not entity or "id" not in entity:
        return None

    notes = entity.get("notes")
    customer_name = notes.get("customer_name") if isinstance(notes, dict) else None

    return ParsedPaymentEvent(
        razorpay_payment_id=entity["id"],
        razorpay_order_id=entity.get("order_id"),
        amount=int(entity.get("amount", 0)),
        currency=entity.get("currency", "INR"),
        method=entity.get("method"),
        email=entity.get("email"),
        contact=entity.get("contact"),
        customer_name=customer_name,
        error_code=entity.get("error_code"),
        error_description=entity.get("error_description"),
        error_source=entity.get("error_source"),
        error_step=entity.get("error_step"),
        error_reason=entity.get("error_reason"),
    )


def derive_failure_class(error_reason: str | None, error_code: str | None) -> str | None:
    """Maps a Razorpay `error.reason` (or, failing that, `error.code`) to the coarser
    `failure_class` bucket used as an ML feature and a policy input. Never invents a reason
    Razorpay didn't give us — an unmapped reason becomes "OTHER", not a guess.
    """
    if not error_reason and not error_code:
        return None

    reason = (error_reason or error_code or "").lower()
    if "insufficient" in reason or "funds" in reason:
        return "INSUFFICIENT_FUNDS"
    if "auth" in reason or "otp" in reason or "3ds" in reason or "password_incorrect" in reason:
        return "AUTH_FAILURE"
    if "timeout" in reason or "gateway" in reason:
        return "GATEWAY_TIMEOUT"
    if "declined" in reason or "issuer" in reason or "bank" in reason:
        return "BANK_DECLINE"
    if "network" in reason:
        return "NETWORK_ERROR"
    if "risk" in reason or "fraud" in reason or "blocked" in reason:
        return "RISK_BLOCKED"
    return "OTHER"
