"""policy_evaluations — one immutable row per (case, candidate action) the deterministic
PolicyEngine ever evaluated, allowed or not. `recovery_actions.policy_evaluation_id` is a
mandatory FK into this table — see recovery_action.py for why that's the concrete enforcement
of "an action cannot bypass policy."
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PolicyEvaluation(Base):
    __tablename__ = "policy_evaluations"
    __table_args__ = (Index("idx_policy_evaluations_case", "recovery_case_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recovery_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recovery_cases.id"), nullable=False
    )
    candidate_action: Mapped[str] = mapped_column(String, nullable=False)
    allowed: Mapped[bool] = mapped_column(nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    expected_value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    policy_version: Mapped[str] = mapped_column(String, nullable=False)

    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
