"""The Revenue Signal Engine: decides whether a reconstructed payment state represents
revenue at risk worth creating a RecoveryOpportunity for, and creates that opportunity.

`revenue_at_risk()` definition — a payment qualifies only if it is:
  * unresolved: `status == FAILED` (not already CAPTURED/REFUNDED)
  * economically meaningful: `amount > settings.min_amount_at_risk_paise`
  * not already the subject of a live case — enforced independently by the partial unique
    index on `recovery_cases.payment_id`, not re-checked here (this function only answers
    "is this payment, in isolation, worth looking at")

The recovery *window* (is it still worth acting on) is a case-level concept
(`recovery_cases.recovery_window_expires_at`), set at case creation — not evaluated here.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.enums import AuditActor, AuditEvent, OpportunityStatus, OpportunityType, PaymentStatus
from app.domain.models.payment import Payment
from app.domain.models.recovery_opportunity import RecoveryOpportunity
from app.repositories.recovery_opportunity_repository import RecoveryOpportunityRepository
from app.services import ledger_service


def revenue_at_risk(payment: Payment) -> bool:
    """Pure predicate — no I/O, so it's directly unit-testable against an in-memory Payment
    instance without a database."""
    settings = get_settings()
    if payment.status != PaymentStatus.FAILED.value:
        return False
    if payment.amount <= settings.min_amount_at_risk_paise:
        return False
    return True


async def detect_opportunity(
    session: AsyncSession, payment: Payment, correlation_id: uuid.UUID
) -> RecoveryOpportunity | None:
    """Creates a RecoveryOpportunity for `payment` if it's at risk and doesn't already have
    one of this type. Returns None if not at risk, or if one already exists (idempotent —
    a payment.failed webhook redelivered after the opportunity already exists is a no-op
    here, not a duplicate creation)."""
    if not revenue_at_risk(payment):
        return None

    repo = RecoveryOpportunityRepository(session)
    existing = await repo.get_by_payment_and_type(
        payment.id, OpportunityType.ONE_TIME_PAYMENT_FAILURE.value
    )
    if existing:
        return None

    opportunity = await repo.add(
        RecoveryOpportunity(
            payment_id=payment.id,
            customer_id=payment.customer_id,
            opportunity_type=OpportunityType.ONE_TIME_PAYMENT_FAILURE.value,
            amount_at_risk=payment.amount,
            currency=payment.currency,
            detected_at=datetime.now(UTC),
            status=OpportunityStatus.OPEN.value,
        )
    )
    await ledger_service.record(
        session,
        correlation_id=correlation_id,
        entity_type="recovery_opportunity",
        entity_id=opportunity.id,
        event=AuditEvent.REVENUE_DETECTED,
        actor=AuditActor.SYSTEM,
        details={"payment_id": str(payment.id), "amount_at_risk": payment.amount},
    )
    return opportunity


def recovery_window_expiry(detected_at: datetime) -> datetime:
    settings = get_settings()
    return detected_at + timedelta(hours=settings.recovery_window_hours)
