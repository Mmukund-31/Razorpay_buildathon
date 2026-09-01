"""recovery_opportunities — a detected instance of revenue at risk, before it becomes a
worked case. See app/services/revenue_signal_service.py for the eligibility definition
(docs/architecture.md's `revenue_at_risk()`).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import OpportunityStatus, OpportunityType


class RecoveryOpportunity(Base):
    __tablename__ = "recovery_opportunities"
    __table_args__ = (
        CheckConstraint(
            f"opportunity_type IN ({','.join(repr(s.value) for s in OpportunityType)})",
            name="ck_recovery_opportunities_type",
        ),
        CheckConstraint(
            f"status IN ({','.join(repr(s.value) for s in OpportunityStatus)})",
            name="ck_recovery_opportunities_status",
        ),
        UniqueConstraint(
            "payment_id", "opportunity_type", name="uq_recovery_opportunities_payment_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )
    opportunity_type: Mapped[str] = mapped_column(String, nullable=False)
    amount_at_risk: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhook_events.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default=OpportunityStatus.OPEN.value)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
