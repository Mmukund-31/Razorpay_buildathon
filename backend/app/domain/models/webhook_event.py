"""webhook_events — the raw, immutable ingestion log. Every Razorpay (or simulator) webhook
lands here first, before any business logic runs.

Idempotency: `razorpay_event_id` UNIQUE. A retried Razorpay delivery (at-least-once, per their
docs) hits an IntegrityError on insert; the ingestion service catches it and acks 200 without
reprocessing — see app/services/event_ingestion_service.py and docs/razorpay-integration.md.

Ordering: `sequence_id` is a local monotonic tie-breaker for when `razorpay_created_at`
collides or delivery arrives out of order (Razorpay does not guarantee delivery order).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import WebhookProcessingStatus


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        CheckConstraint(
            f"processing_status IN ({','.join(repr(s.value) for s in WebhookProcessingStatus)})",
            name="ck_webhook_events_processing_status",
        ),
        Index("idx_webhook_events_status_seq", "processing_status", "sequence_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    razorpay_event_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # Identity(always=False) matches the migration's DDL exactly — without it SQLAlchemy
    # doesn't know this is server-generated and includes an explicit NULL in the INSERT
    # column list instead of omitting it, which Postgres rejects (found by running the real
    # integration tests against a live database: NotNullViolationError on sequence_id).
    sequence_id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), unique=True)

    event_type: Mapped[str] = mapped_column(String, nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    raw_body: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    razorpay_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    processing_status: Mapped[str] = mapped_column(
        String, nullable=False, default=WebhookProcessingStatus.PENDING.value
    )
    processing_error: Mapped[str | None] = mapped_column(String, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
