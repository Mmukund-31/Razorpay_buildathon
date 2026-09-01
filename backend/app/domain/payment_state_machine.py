"""The payment state machine: CREATED/AUTHORIZED/CAPTURED/FAILED/REFUNDED/UNKNOWN.

Deliberately pure, in-memory logic with **zero I/O** — this is what makes it independently
unit-testable and what makes a bug here impossible to hide behind a flaky DB fixture. The
conditional-UPDATE SQL pattern that applies this decision durably (`WHERE id=:id AND
is_terminal=false AND (last_event_created_at,last_event_sequence_id) < (:evt_ts,:evt_seq)`)
lives in the repository layer (Phase 2, `app/repositories/payment_repository.py`) and must
call `apply_event()` first to decide *what* to write, then issue that guarded UPDATE — never
a blind `.status = x`.

Verified Razorpay quirks this table encodes (see docs/razorpay-integration.md):
  * `payment.failed` never fires on the very first checkout authorization failure — only once
    an order/payment entity already exists.
  * A `payment.failed` can be followed later by `payment.captured` for the *same*
    `payment_id` (UPI: customer corrects a wrong PIN and retries inside their UPI app).
  * Webhook delivery order is not guaranteed — hence the ordering guard below.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.domain.enums import PAYMENT_TERMINAL_STATUSES, PaymentStatus

IgnoredReason = Literal["TERMINAL", "STALE", "NONE"]

# (from_status, event_type) -> to_status. Anything not listed here, fired at a non-terminal
# state, degrades gracefully to UNKNOWN rather than being rejected outright — an event type
# we don't recognize yet shouldn't corrupt or freeze the payment's reconstructed state.
_TRANSITIONS: dict[tuple[PaymentStatus, str], PaymentStatus] = {
    (PaymentStatus.CREATED, "payment.authorized"): PaymentStatus.AUTHORIZED,
    (PaymentStatus.CREATED, "order.paid"): PaymentStatus.AUTHORIZED,
    (PaymentStatus.CREATED, "payment.failed"): PaymentStatus.FAILED,
    (PaymentStatus.AUTHORIZED, "payment.failed"): PaymentStatus.FAILED,
    (PaymentStatus.AUTHORIZED, "payment.captured"): PaymentStatus.CAPTURED,
    (PaymentStatus.AUTHORIZED, "order.paid"): PaymentStatus.CAPTURED,
    (PaymentStatus.FAILED, "payment.captured"): PaymentStatus.CAPTURED,  # verified UPI quirk
    (PaymentStatus.CAPTURED, "payment.refunded"): PaymentStatus.REFUNDED,
}

_RECOGNIZED_EVENT_TYPES = frozenset(event_type for _, event_type in _TRANSITIONS)


@dataclass(frozen=True, slots=True)
class PaymentSnapshot:
    status: PaymentStatus
    is_terminal: bool
    last_event_created_at: datetime | None
    last_event_sequence_id: int | None


@dataclass(frozen=True, slots=True)
class PaymentEvent:
    event_type: str
    created_at: datetime
    sequence_id: int


@dataclass(frozen=True, slots=True)
class PaymentTransitionResult:
    applied: bool
    new_status: PaymentStatus | None
    new_is_terminal: bool | None
    ignored_reason: IgnoredReason


def apply_event(snapshot: PaymentSnapshot, event: PaymentEvent) -> PaymentTransitionResult:
    """Decide the new payment status for `event`, or explain why it was ignored.

    Never mutates anything — the caller is responsible for durably persisting the result via
    a conditional UPDATE guarded by the same watermark fields checked here.
    """
    if snapshot.is_terminal:
        return PaymentTransitionResult(False, None, None, "TERMINAL")

    if snapshot.last_event_created_at is not None and snapshot.last_event_sequence_id is not None:
        incoming = (event.created_at, event.sequence_id)
        watermark = (snapshot.last_event_created_at, snapshot.last_event_sequence_id)
        if incoming <= watermark:
            return PaymentTransitionResult(False, None, None, "STALE")

    to_status = _TRANSITIONS.get((snapshot.status, event.event_type))
    if to_status is None:
        to_status = PaymentStatus.UNKNOWN

    return PaymentTransitionResult(
        applied=True,
        new_status=to_status,
        new_is_terminal=to_status in PAYMENT_TERMINAL_STATUSES,
        ignored_reason="NONE",
    )


def can_transition(snapshot: PaymentSnapshot, event: PaymentEvent) -> bool:
    return apply_event(snapshot, event).applied
