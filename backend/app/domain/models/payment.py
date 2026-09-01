"""payments — the reconstructed state of a Razorpay payment entity.

`last_event_created_at` / `last_event_sequence_id` are the ordering watermark that makes the
"a stale event cannot overwrite a newer terminal state" invariant enforceable: every write to
`status` MUST go through a conditional UPDATE guarded by these two columns (see
app/domain/payment_state_machine.py), never a blind ORM `.status = x; session.commit()`.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import PaymentStatus


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({','.join(repr(s.value) for s in PaymentStatus)})",
            name="ck_payments_status",
        ),
        Index("idx_payments_customer", "customer_id"),
        Index("idx_payments_status", "status"),
        Index("idx_payments_order", "razorpay_order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    razorpay_payment_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    razorpay_order_id: Mapped[str | None] = mapped_column(String, nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )

    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # smallest currency unit (paise)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String, nullable=False, default=PaymentStatus.CREATED.value)
    method: Mapped[str | None] = mapped_column(String, nullable=True)

    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_description: Mapped[str | None] = mapped_column(String, nullable=True)
    error_source: Mapped[str | None] = mapped_column(String, nullable=True)
    error_step: Mapped[str | None] = mapped_column(String, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_class: Mapped[str | None] = mapped_column(String, nullable=True)  # derived, see ml-evaluation.md

    last_event_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_sequence_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    raw_entity: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
