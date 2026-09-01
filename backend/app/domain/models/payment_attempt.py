"""payment_attempts — one row per distinct checkout attempt against a payment/order.

Distinct from `webhook_events` (raw ingestion log): this is the reconstructed, deduplicated
attempt history used as ML features (attempt_count, time_since_last_attempt, etc.).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        UniqueConstraint("payment_id", "attempt_number", name="uq_payment_attempts_payment_attempt"),
        Index("idx_payment_attempts_payment", "payment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False
    )
    razorpay_order_id: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    method: Mapped[str | None] = mapped_column(String, nullable=True)

    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_description: Mapped[str | None] = mapped_column(String, nullable=True)
    error_source: Mapped[str | None] = mapped_column(String, nullable=True)
    error_step: Mapped[str | None] = mapped_column(String, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
