"""Orchestrates recovery_opportunities -> recovery_cases and drives the case through
app/domain/recovery_case_state_machine.py, durably (optimistic-locked UPDATE guarded by
`version`). Every transition here re-reads `payments.status` fresh from the database before
calling `apply_trigger()` — never a cached flag — per that module's docstring.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.enums import ActionType, AuditActor, AuditEvent, PaymentStatus, RecoveryCaseStatus
from app.domain.models.customer import Customer
from app.domain.models.payment import Payment
from app.domain.models.recovery_case import RecoveryCase
from app.domain.models.recovery_opportunity import RecoveryOpportunity
from app.domain.recovery_case_state_machine import (
    CaseTrigger,
    RecoveryCaseSnapshot,
    apply_trigger,
)
from app.repositories.recovery_case_repository import RecoveryCaseRepository
from app.services import ledger_service
from app.services.revenue_signal_service import recovery_window_expiry

logger = get_logger(__name__)

_CASE_EVENT_BY_TARGET_STATUS: dict[RecoveryCaseStatus, AuditEvent] = {
    RecoveryCaseStatus.ABSTAINED: AuditEvent.CASE_ABSTAINED,
    RecoveryCaseStatus.EXPIRED: AuditEvent.CASE_EXPIRED,
    RecoveryCaseStatus.ESCALATED: AuditEvent.CASE_ESCALATED,
    RecoveryCaseStatus.SUCCEEDED: AuditEvent.PAYMENT_RECOVERED,
    RecoveryCaseStatus.POLICY_APPROVED: AuditEvent.POLICY_APPROVED,
    RecoveryCaseStatus.POLICY_REJECTED: AuditEvent.POLICY_REJECTED,
}


class ConcurrentTransitionLost(Exception):
    """Raised when the optimistic lock loses a race even after one retry. The caller should
    treat this as "someone else already moved this case" and simply stop, not error out."""


async def create_case_from_opportunity(
    session: AsyncSession, opportunity: RecoveryOpportunity, correlation_id: uuid.UUID
) -> RecoveryCase:
    case = RecoveryCase(
        opportunity_id=opportunity.id,
        payment_id=opportunity.payment_id,
        customer_id=opportunity.customer_id,
        status=RecoveryCaseStatus.DETECTED.value,
        amount=opportunity.amount_at_risk,
        currency=opportunity.currency,
        attempt_count=0,
        max_attempts=get_settings().max_retries,
        recovery_window_expires_at=recovery_window_expiry(opportunity.detected_at),
        version=0,
    )
    session.add(case)
    await session.flush()
    return case


async def _payment_captured(session: AsyncSession, payment_id: uuid.UUID) -> bool:
    payment = await session.get(Payment, payment_id)
    return bool(payment and payment.status == PaymentStatus.CAPTURED.value)


async def transition(
    session: AsyncSession,
    case: RecoveryCase,
    trigger: CaseTrigger,
    correlation_id: uuid.UUID,
    *,
    action_type: ActionType | None = None,
    consent_recorded: bool = True,
    extra_fields: dict | None = None,
    max_retries: int = 1,
    resolved_payment_id: uuid.UUID | None = None,
) -> RecoveryCase:
    """Applies one trigger to `case`, retrying once on an optimistic-lock loss (another
    worker raced us) by re-reading the case and recomputing — never blindly re-applying the
    same stale decision.

    `resolved_payment_id`: freshly checked instead of `case.payment_id` when given — for the
    payment-link-recovery case (app/services/outcome_service.py), the payment that actually
    got captured is a DIFFERENT row than the case's original (failed) `payment_id`, which
    itself never becomes CAPTURED. This is not a cached shortcut: the caller passes the id of
    a payment it just read fresh in this same request, so the "always re-check live state,
    never trust a stale flag" invariant this function's docstring promises still holds — the
    check below still re-reads `payments.status` from the database on every loop iteration.
    """
    for attempt in range(max_retries + 1):
        payment_captured = await _payment_captured(session, resolved_payment_id or case.payment_id)
        snapshot = RecoveryCaseSnapshot(
            status=RecoveryCaseStatus(case.status),
            attempt_count=case.attempt_count,
            max_attempts=case.max_attempts,
            version=case.version,
        )
        decision = apply_trigger(
            snapshot,
            trigger,
            payment_captured=payment_captured,
            action_type=action_type,
            consent_recorded=consent_recorded,
        )
        if not decision.applied:
            logger.info(
                "recovery case transition rejected",
                extra={"case_id": str(case.id), "trigger": trigger.value, "reason": decision.ignored_reason},
            )
            return case

        assert decision.new_status is not None  # guaranteed by CaseTransitionResult when applied=True

        repo = RecoveryCaseRepository(session)
        fields = dict(extra_fields or {})
        applied = await repo.apply_state_transition(
            case_id=case.id,
            expected_version=case.version,
            new_status=decision.new_status.value,
            extra_fields=fields,
        )
        if applied:
            await session.refresh(case)
            ledger_event = _CASE_EVENT_BY_TARGET_STATUS.get(decision.new_status)
            if ledger_event:
                await ledger_service.record(
                    session,
                    correlation_id=correlation_id,
                    entity_type="recovery_case",
                    entity_id=case.id,
                    event=ledger_event,
                    actor=AuditActor.SYSTEM,
                    decision=decision.new_status.value,
                    reason=decision.ignored_reason if decision.ignored_reason != "NONE" else None,
                    details={"trigger": trigger.value, "forced": decision.forced},
                )
            return case

        if attempt < max_retries:
            await session.refresh(case)
            continue
        raise ConcurrentTransitionLost(f"case {case.id} version moved during transition")

    return case  # unreachable, satisfies type checkers


async def evaluate_eligibility(
    session: AsyncSession, case: RecoveryCase, correlation_id: uuid.UUID
) -> RecoveryCase:
    """DETECTED -> ELIGIBLE, or ABSTAINED (opted out) / EXPIRED (window passed)."""
    payment = await session.get(Payment, case.payment_id)
    customer_id = payment.customer_id if payment else None
    if customer_id:
        customer = await session.get(Customer, customer_id)
        if customer and customer.opted_out:
            return await transition(
                session, case, CaseTrigger.CUSTOMER_OPTED_OUT, correlation_id
            )

    if case.recovery_window_expires_at and datetime.now(UTC) >= case.recovery_window_expires_at:
        return await transition(session, case, CaseTrigger.WINDOW_EXPIRED, correlation_id)

    return await transition(session, case, CaseTrigger.ELIGIBILITY_PASSED, correlation_id)
