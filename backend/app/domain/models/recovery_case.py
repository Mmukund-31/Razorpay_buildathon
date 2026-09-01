"""recovery_cases — the working unit the whole pipeline operates on, from DETECTED to a
terminal state. See app/domain/recovery_case_state_machine.py for the transition rules this
schema exists to support.

Two independent safety mechanisms live here:
  1. The partial unique index below guarantees at most one *live* case per payment — the
     schema-level enforcement of "a payment cannot be recovered twice."
  2. `version` is an optimistic-lock column: every transition is a
     `WHERE id=:id AND version=:expected` UPDATE, so two concurrently-processing webhooks
     can never double-transition the same case.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import RecoveryCaseStatus

_LIVE_STATUSES = ("FAILED", "EXPIRED", "ABSTAINED")


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({','.join(repr(s.value) for s in RecoveryCaseStatus)})",
            name="ck_recovery_cases_status",
        ),
        UniqueConstraint("opportunity_id", name="uq_recovery_cases_opportunity"),
        Index("idx_recovery_cases_status", "status"),
        Index("idx_recovery_cases_payment", "payment_id"),
        Index(
            "uq_recovery_cases_one_live_per_payment",
            "payment_id",
            unique=True,
            postgresql_where=text(f"status NOT IN {_LIVE_STATUSES}"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recovery_opportunities.id"), nullable=False
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default=RecoveryCaseStatus.DETECTED.value)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    recovery_window_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    selected_action: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
