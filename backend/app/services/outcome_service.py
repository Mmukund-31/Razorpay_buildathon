"""The Outcome Engine: reconciles a `payment.captured` (or `payment_link.paid`) signal back
onto the RecoveryCase that caused it, even when the captured payment has a DIFFERENT
`razorpay_payment_id` than the case's originating (failed) payment — the normal outcome for
SMART_RETRY/DELAYED_RETRY/CUSTOMER_ACTION_REQUEST, which all resolve to creating a fresh
Razorpay Payment Link rather than "retrying" the original payment (there is no such API — see
docs/razorpay-integration.md §4).

Two resolution paths, tried in order:

1. **Same-payment-id path** — the captured payment IS the case's original `payment_id` (the
   verified UPI wrong-PIN-then-retry quirk). No correlation needed; this is what
   `RecoveryCaseRepository.get_live_case_for_payment()` already finds.
2. **Payment-link correlation path** — the captured payment is a brand-new row whose
   `recovery_action_id` was resolved from the Payment Link's `reference_id` at reconstruction
   time (`app/services/state_reconstruction_service.py`, `app/domain/recovery_action_reference.py`).

Every write here is idempotent: re-processing the same or a re-delivered duplicate webhook
must never double-write `actual_recovered_amount`, never re-fire the case transition beyond
what the state machine already allows, and never regress an already-terminal case. This
mirrors the same conditional-UPDATE discipline `PaymentRepository`/`RecoveryCaseRepository`
already use elsewhere — no new idempotency mechanism invented here.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.enums import (
    RECOVERY_CASE_TERMINAL_STATUSES,
    AuditActor,
    AuditEvent,
    RecoveryActionStatus,
    RecoveryCaseStatus,
)
from app.domain.models.payment import Payment
from app.domain.models.recovery_action import RecoveryAction
from app.domain.models.recovery_case import RecoveryCase
from app.domain.recovery_case_state_machine import CaseTrigger
from app.repositories.recovery_action_repository import RecoveryActionRepository
from app.repositories.recovery_case_repository import RecoveryCaseRepository
from app.services import ledger_service, recovery_case_service

logger = get_logger(__name__)


async def reconcile_outcome(
    session: AsyncSession, payment: Payment, correlation_id: uuid.UUID
) -> RecoveryCase | None:
    """`payment.status` must already be CAPTURED (caller's responsibility — this mirrors the
    contract `pipeline_orchestrator.py::_resolve_if_captured` already enforced before
    delegating here). Returns the resolved case, or None if no case could be correlated at
    all (an organic payment with no recovery history — not an error)."""
    case_repo = RecoveryCaseRepository(session)

    case = await case_repo.get_live_case_for_payment(payment.id)

    if case is None and payment.recovery_action_id is not None:
        action = await session.get(RecoveryAction, payment.recovery_action_id)
        if action is not None:
            case = await session.get(RecoveryCase, action.recovery_case_id)

    if case is None:
        return None

    if RecoveryCaseStatus(case.status) in RECOVERY_CASE_TERMINAL_STATUSES:
        # Already resolved (or otherwise terminally closed) by an earlier delivery of this
        # same signal, or a race with another worker — the state machine's own
        # payment_captured guard would reject a re-fired transition anyway; this is a named,
        # audited no-op rather than a silent one.
        await ledger_service.record(
            session,
            correlation_id=correlation_id,
            entity_type="recovery_case",
            entity_id=case.id,
            event=AuditEvent.EVENT_IGNORED_STALE,
            actor=AuditActor.SYSTEM,
            reason="CASE_ALREADY_TERMINAL",
            details={"payment_id": str(payment.id)},
        )
        return case

    if payment.currency != case.currency:
        # A genuine data-integrity red flag (a payment link is always created in the case's
        # own currency — see payment_link_adapter.py) — log it and refuse to resolve rather
        # than silently recording a cross-currency "recovery."
        await ledger_service.record(
            session,
            correlation_id=correlation_id,
            entity_type="recovery_case",
            entity_id=case.id,
            event=AuditEvent.EVENT_IGNORED_STALE,
            actor=AuditActor.SYSTEM,
            reason="CURRENCY_MISMATCH",
            details={
                "payment_id": str(payment.id),
                "payment_currency": payment.currency,
                "case_currency": case.currency,
            },
        )
        return case

    # Idempotent, write-once amount recording — a conditional UPDATE guarded by
    # `actual_recovered_amount IS NULL`, mirroring PaymentRepository's watermark-guard
    # pattern. `written=False` means another worker (or a duplicate delivery processed
    # concurrently) already recorded it — a safe no-op, never a second write.
    written = await case_repo.set_actual_recovered_amount(
        case_id=case.id, amount=payment.amount, resolved_payment_id=payment.id
    )
    if written:
        await session.refresh(case)
    else:
        logger.info(
            "actual_recovered_amount already recorded — idempotent no-op",
            extra={"case_id": str(case.id)},
        )

    case = await recovery_case_service.transition(
        session,
        case,
        CaseTrigger.PAYMENT_CAPTURED_EXTERNALLY,
        correlation_id,
        resolved_payment_id=payment.id,
    )

    await _cancel_pending_actions_for_case(session, case.id, correlation_id)

    return case


async def _cancel_pending_actions_for_case(
    session: AsyncSession, recovery_case_id: uuid.UUID, correlation_id: uuid.UUID
) -> None:
    """Once a case resolves, any still-PENDING action (only ever a not-yet-dispatched
    DELAYED_RETRY — see app/services/execution_service.py's two-step dispatch) is now moot:
    the payment already came in through a different path. Skip it rather than let the
    background worker's scheduled sweep dispatch a redundant Payment Link later. Already
    SUCCEEDED/FAILED rows are historical fact and are left untouched."""
    action_repo = RecoveryActionRepository(session)
    for action in await action_repo.list_for_case(recovery_case_id):
        if action.status != RecoveryActionStatus.PENDING.value:
            continue
        action.status = RecoveryActionStatus.SKIPPED.value
        await session.flush()
        await ledger_service.record(
            session,
            correlation_id=correlation_id,
            entity_type="recovery_action",
            entity_id=action.id,
            event=AuditEvent.ACTION_SKIPPED,
            actor=AuditActor.SYSTEM,
            decision="SKIPPED",
            reason="CASE_ALREADY_RESOLVED",
        )
