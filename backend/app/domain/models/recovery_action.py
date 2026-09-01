"""recovery_actions — one row per executed (or skipped) intervention.

Three independent safety mechanisms live on this table:
  1. `action_type` CHECK constraint mirrors the 7-value ActionType allowlist — a second,
     independent layer beyond the Pydantic validation the executor does before dispatch.
  2. `idempotency_key` UNIQUE (deterministic: f"{case_id}:{action_type}:{attempt_count}") —
     a duplicate execution attempt for the same key fails at insert, treated as already-handled.
  3. `policy_evaluation_id` is NOT NULL — there is no code path that constructs a row here
     without first joining an approved policy_evaluations record. This is the concrete
     enforcement of "an action cannot bypass policy."
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import ActionType, RecoveryActionStatus


class RecoveryAction(Base):
    __tablename__ = "recovery_actions"
    __table_args__ = (
        CheckConstraint(
            f"action_type IN ({','.join(repr(s.value) for s in ActionType)})",
            name="ck_recovery_actions_action_type",
        ),
        CheckConstraint(
            f"status IN ({','.join(repr(s.value) for s in RecoveryActionStatus)})",
            name="ck_recovery_actions_status",
        ),
        Index("idx_recovery_actions_case", "recovery_case_id"),
        # `external_reference` (the Razorpay Payment Link id) is a lookup key now, not just a
        # display field — see app/services/outcome_service.py's fallback correlation path.
        Index("idx_recovery_actions_external_reference", "external_reference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recovery_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recovery_cases.id"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default=RecoveryActionStatus.PENDING.value)
    channel: Mapped[str | None] = mapped_column(String, nullable=True)  # sms|email|voice|payment_link|api

    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    external_reference: Mapped[str | None] = mapped_column(String, nullable=True)  # Razorpay plink/order id
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    consent_recorded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    policy_evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_evaluations.id"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
