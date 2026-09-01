"""POST /api/webhooks/razorpay — signature verification and idempotent persistence are REAL.

Flow (per docs/razorpay-integration.md's verified webhook contract):
  raw bytes -> verify X-Razorpay-Signature (HMAC-SHA256 over the RAW body) -> reject with 400
  if invalid -> parse JSON only after verification -> dedupe on x-razorpay-event-id (insert,
  catch IntegrityError as idempotent no-op) -> persist to webhook_events -> ack 200.

Deliberately NO business logic runs inline here — Razorpay requires a 2xx within ~5s, so
everything past persistence (state reconstruction, ML, AI) happens in the background worker
(app/core/background_worker.py), which is still a stub in Phase 1. This endpoint's job ends
at "the event is durably and exactly-once recorded."
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Header, Request, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.domain.enums import WebhookProcessingStatus
from app.domain.models.webhook_event import WebhookEvent
from app.integrations.webhook_verifier import verify_signature

router = APIRouter()
logger = get_logger(__name__)


@router.post("/webhooks/razorpay", status_code=status.HTTP_200_OK)
async def receive_razorpay_webhook(
    request: Request,
    db: DbSession,
    x_razorpay_signature: str | None = Header(default=None),
    x_razorpay_event_id: str | None = Header(default=None),
) -> dict:
    raw_body = await request.body()
    settings = get_settings()

    signature_valid = verify_signature(
        raw_body, x_razorpay_signature or "", settings.razorpay_webhook_secret
    )
    if not signature_valid:
        raise AppError(
            code="INVALID_WEBHOOK_SIGNATURE",
            message="Webhook signature verification failed.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not x_razorpay_event_id:
        raise AppError(
            code="MISSING_EVENT_ID",
            message="X-Razorpay-Event-Id header is required.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    payload = await request.json()
    event_type = payload.get("event", "unknown")
    razorpay_created_at = payload.get("created_at")
    razorpay_created_at_dt = (
        datetime.fromtimestamp(razorpay_created_at, tz=UTC)
        if isinstance(razorpay_created_at, int | float)
        else datetime.now(UTC)
    )

    event = WebhookEvent(
        razorpay_event_id=x_razorpay_event_id,
        event_type=event_type,
        signature_valid=True,
        raw_body=raw_body,
        headers=dict(request.headers),
        payload=payload,
        razorpay_created_at=razorpay_created_at_dt,
        processing_status=WebhookProcessingStatus.PENDING.value,
    )
    db.add(event)
    try:
        await db.commit()
    except IntegrityError:
        # Duplicate delivery (Razorpay's at-least-once semantics) — idempotent no-op ack,
        # never a second row, never reprocessed.
        await db.rollback()
        logger.info(
            "duplicate webhook event ignored",
            extra={"razorpay_event_id": x_razorpay_event_id, "event_type": event_type},
        )
        return {"status": "ok", "duplicate": True}

    return {"status": "ok", "duplicate": False}
