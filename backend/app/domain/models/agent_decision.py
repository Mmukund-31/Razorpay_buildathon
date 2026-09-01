"""agent_decisions — every ML prediction and every AI diagnosis, valid or not.

`is_valid` is the concrete enforcement of "malformed AI output can't reach executor": the
optimizer (app/services/optimizer_service.py) only ever reads `validated_output` on rows where
`is_valid=true`. A row with `is_valid=false` is recorded for audit/debugging but treated as
"no signal," never as a fallback instruction.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import AgentDecisionType


class AgentDecision(Base):
    __tablename__ = "agent_decisions"
    __table_args__ = (
        CheckConstraint(
            f"decision_type IN ({','.join(repr(s.value) for s in AgentDecisionType)})",
            name="ck_agent_decisions_decision_type",
        ),
        Index("idx_agent_decisions_case", "recovery_case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recovery_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recovery_cases.id"), nullable=False
    )
    decision_type: Mapped[str] = mapped_column(String, nullable=False)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_versions.id"), nullable=True
    )
    input_features: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_output: Mapped[dict] = mapped_column(JSONB, nullable=False)
    validated_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
