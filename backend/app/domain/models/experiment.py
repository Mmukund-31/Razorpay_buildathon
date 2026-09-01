"""experiments — one row per benchmark run of a baseline (or the full RecoveryOS stack)
against a dataset. See simulator/benchmark/baseline_runner.py (Phase 18)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import BaselineType


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint(
            f"baseline_type IN ({','.join(repr(s.value) for s in BaselineType)})",
            name="ck_experiments_baseline_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    baseline_type: Mapped[str] = mapped_column(String, nullable=False)
    dataset_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Set only for a bounded-sample run (currently RECOVERYOS_AI — see
    # simulator/benchmark/baseline_runner.py) so the run self-documents that it evaluated a
    # subset, not the full dataset, at the persistence layer rather than only in prose.
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sampling_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
