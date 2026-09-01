"""Isolates the DB-constraint half of webhook idempotency: a duplicate razorpay_event_id must
raise IntegrityError. The other half — that the ingestion layer catches this and acks 200
without a second row, rather than propagating a 500 — is verified end-to-end in
tests/integration/test_webhook_ingestion.py. Needs a real database (the constraint being
tested only exists once the schema is migrated); skips gracefully without one via the
`db_session` fixture — see tests/conftest.py.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.enums import WebhookProcessingStatus
from app.domain.models.webhook_event import WebhookEvent

pytestmark = pytest.mark.unit


def _make_event(event_id: str) -> WebhookEvent:
    return WebhookEvent(
        razorpay_event_id=event_id,
        event_type="payment.failed",
        signature_valid=True,
        raw_body=b"{}",
        payload={},
        razorpay_created_at=datetime.now(UTC),
        processing_status=WebhookProcessingStatus.PENDING.value,
    )


@pytest.mark.asyncio
async def test_duplicate_razorpay_event_id_raises_integrity_error(db_session):
    event_id = f"evt_test_{uuid.uuid4().hex}"

    db_session.add(_make_event(event_id))
    await db_session.commit()

    db_session.add(_make_event(event_id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
