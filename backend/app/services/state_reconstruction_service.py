"""Applies app/domain/payment_state_machine.py's decision durably: reads the current
PaymentSnapshot, calls `apply_event()`, and issues the guarded conditional UPDATE via
PaymentRepository.apply_state_transition() — never a blind `.status = x`.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.enums import AuditActor, AuditEvent, PaymentStatus
from app.domain.models.customer import Customer
from app.domain.models.payment import Payment
from app.domain.models.payment_attempt import PaymentAttempt
from app.domain.models.webhook_event import WebhookEvent
from app.domain.payment_state_machine import PaymentEvent, PaymentSnapshot, apply_event
from app.repositories.customer_repository import CustomerRepository
from app.repositories.payment_repository import PaymentRepository
from app.services import ledger_service
from app.services.razorpay_payload_parser import derive_failure_class, parse_payment_entity

logger = get_logger(__name__)


async def _find_or_create_customer(
    session: AsyncSession, *, email: str | None, contact: str | None, name: str | None
) -> Customer | None:
    if not email and not contact:
        return None
    repo = CustomerRepository(session)
    existing = await repo.get_by_phone_or_email(phone=contact, email=email)
    if existing:
        return existing
    return await repo.add(Customer(email=email, phone=contact, name=name))


async def _find_or_create_payment(
    session: AsyncSession, *, razorpay_payment_id: str, amount: int, currency: str
) -> Payment:
    repo = PaymentRepository(session)
    existing = await repo.get_by_razorpay_id(razorpay_payment_id)
    if existing:
        return existing
    return await repo.add(
        Payment(
            razorpay_payment_id=razorpay_payment_id,
            amount=amount,
            currency=currency,
            status=PaymentStatus.CREATED.value,
            is_terminal=False,
        )
    )


async def apply(
    session: AsyncSession, webhook_event: WebhookEvent, correlation_id: uuid.UUID
) -> Payment | None:
    """Reconstructs payment state from one webhook event. Returns the (possibly unchanged)
    Payment row, or None if the payload carried no payment entity at all (e.g. a
    subscription.* event — out of scope for state reconstruction, handled separately).
    """
    parsed = parse_payment_entity(webhook_event.payload)
    if parsed is None:
        return None

    customer = await _find_or_create_customer(
        session, email=parsed.email, contact=parsed.contact, name=parsed.customer_name
    )
    payment = await _find_or_create_payment(
        session,
        razorpay_payment_id=parsed.razorpay_payment_id,
        amount=parsed.amount,
        currency=parsed.currency,
    )
    if customer and payment.customer_id is None:
        payment.customer_id = customer.id
        await session.flush()

    snapshot = PaymentSnapshot(
        status=PaymentStatus(payment.status),
        is_terminal=payment.is_terminal,
        last_event_created_at=payment.last_event_created_at,
        last_event_sequence_id=payment.last_event_sequence_id,
    )
    event = PaymentEvent(
        event_type=webhook_event.event_type,
        created_at=webhook_event.razorpay_created_at,
        sequence_id=webhook_event.sequence_id,
    )
    decision = apply_event(snapshot, event)

    if not decision.applied:
        await ledger_service.record(
            session,
            correlation_id=correlation_id,
            entity_type="payment",
            entity_id=payment.id,
            event=AuditEvent.EVENT_IGNORED_STALE,
            actor=AuditActor.SYSTEM,
            reason=decision.ignored_reason,
            details={"webhook_event_id": str(webhook_event.id), "event_type": webhook_event.event_type},
        )
        return payment

    assert decision.new_status is not None  # guaranteed by PaymentTransitionResult when applied=True

    failure_class = derive_failure_class(parsed.error_reason, parsed.error_code)
    repo = PaymentRepository(session)
    applied = await repo.apply_state_transition(
        payment_id=payment.id,
        new_status=decision.new_status.value,
        event_created_at=event.created_at,
        event_sequence_id=event.sequence_id,
        is_terminal=decision.new_is_terminal or False,
        extra_fields={
            "method": parsed.method,
            "error_code": parsed.error_code,
            "error_description": parsed.error_description,
            "error_source": parsed.error_source,
            "error_step": parsed.error_step,
            "error_reason": parsed.error_reason,
            "failure_class": failure_class,
            "raw_entity": webhook_event.payload,
        },
    )

    if not applied:
        # Lost a race to a concurrent worker that already advanced this payment past our
        # watermark between our read and our write — same safe outcome as STALE.
        await ledger_service.record(
            session,
            correlation_id=correlation_id,
            entity_type="payment",
            entity_id=payment.id,
            event=AuditEvent.EVENT_IGNORED_STALE,
            actor=AuditActor.SYSTEM,
            reason="CONCURRENT_UPDATE_LOST_RACE",
        )
        await session.refresh(payment)
        return payment

    last_attempt_number = (
        await session.execute(
            select(PaymentAttempt.attempt_number)
            .where(PaymentAttempt.payment_id == payment.id)
            .order_by(PaymentAttempt.attempt_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    session.add(
        PaymentAttempt(
            payment_id=payment.id,
            razorpay_order_id=parsed.razorpay_order_id,
            attempt_number=(last_attempt_number or 0) + 1,
            status=decision.new_status.value,
            method=parsed.method,
            error_code=parsed.error_code,
            error_description=parsed.error_description,
            error_source=parsed.error_source,
            error_step=parsed.error_step,
            error_reason=parsed.error_reason,
            occurred_at=event.created_at,
        )
    )

    ledger_event = (
        AuditEvent.PAYMENT_FAILED
        if decision.new_status == PaymentStatus.FAILED
        else AuditEvent.PAYMENT_STATE_CHANGED
    )
    await ledger_service.record(
        session,
        correlation_id=correlation_id,
        entity_type="payment",
        entity_id=payment.id,
        event=ledger_event,
        actor=AuditActor.SYSTEM,
        details={"from_status": snapshot.status.value, "to_status": decision.new_status.value},
    )

    await session.refresh(payment)
    return payment
