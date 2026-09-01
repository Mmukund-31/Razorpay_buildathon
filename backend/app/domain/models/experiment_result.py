"""experiment_results — the metric values produced by a benchmark run. `metric_name` is drawn
from the fixed metrics vocabulary in docs/ml-evaluation.md (recovered_revenue, recovery_rate,
expected_recovery, revenue_per_intervention, unnecessary_action_rate, avg_attempts, precision,
recall, f1, calibration_error, abstention_rate, policy_rejection_rate,
execution_success_rate, latency_ms_p50, latency_ms_p95).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExperimentResult(Base):
    __tablename__ = "experiment_results"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "metric_name", "segment", name="uq_experiment_results_metric_segment"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("experiments.id"), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String, nullable=False)
    metric_value: Mapped[float] = mapped_column(Numeric, nullable=False)
    segment: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
