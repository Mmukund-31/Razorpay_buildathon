"""Payment persistence, including the conditional-UPDATE that makes the stale-event guard
durable (see app/domain/payment_state_machine.py's docstring for the exact WHERE clause).
"""

import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import CursorResult, literal, or_, select, tuple_, update

from app.domain.models.payment import Payment
from app.repositories.base_repository import BaseRepository


class PaymentRepository(BaseRepository[Payment]):
    model = Payment

    async def get_by_razorpay_id(self, razorpay_payment_id: str) -> Payment | None:
        result = await self.session.execute(
            select(Payment).where(Payment.razorpay_payment_id == razorpay_payment_id)
        )
        return result.scalar_one_or_none()

    async def apply_state_transition(
        self,
        *,
        payment_id: uuid.UUID,
        new_status: str,
        event_created_at: datetime,
        event_sequence_id: int,
        is_terminal: bool,
        extra_fields: dict | None = None,
    ) -> bool:
        """The durable half of the stale-event guard: a blind ORM `.status = x` would let a
        delayed/out-of-order webhook clobber newer state. This UPDATE only ever affects a row
        that is (a) not already terminal and (b) older than the incoming event's watermark —
        exactly mirroring app/domain/payment_state_machine.py's `apply_event()` guard. Zero
        rows affected means the caller should log EVENT_IGNORED_STALE, not retry.
        """
        watermark = tuple_(Payment.last_event_created_at, Payment.last_event_sequence_id)
        stmt = (
            update(Payment)
            .where(
                Payment.id == payment_id,
                Payment.is_terminal.is_(False),
                or_(
                    Payment.last_event_created_at.is_(None),
                    watermark < tuple_(literal(event_created_at), literal(event_sequence_id)),
                ),
            )
            .values(
                status=new_status,
                last_event_created_at=event_created_at,
                last_event_sequence_id=event_sequence_id,
                is_terminal=is_terminal,
                **(extra_fields or {}),
            )
        )
        result = cast(CursorResult, await self.session.execute(stmt))
        return result.rowcount > 0
