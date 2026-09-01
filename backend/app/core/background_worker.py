"""The async, DB-polling background worker.

Polls `webhook_events` for `PENDING` rows ordered by `(razorpay_created_at, sequence_id)` and
hands each to `pipeline_orchestrator.handle_webhook_event` — the full state
reconstruction -> revenue signal -> case -> analysis -> policy -> execution chain. Durability
comes from the DB status column, not in-memory queue state: if the process crashes mid-batch,
a restarted worker simply re-polls `PENDING` rows. This is why Redis is not required for
correctness (see docs/decisions.md ADR-002).

Also sweeps `execution_service.dispatch_due_scheduled_actions()` every poll iteration, so
DELAYED_RETRY actions fire once their `scheduled_for` arrives without a second worker loop.
"""

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.domain.enums import WebhookProcessingStatus
from app.domain.models.webhook_event import WebhookEvent
from app.services import execution_service, pipeline_orchestrator

logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 2.0
BATCH_SIZE = 25

EventHandler = Callable[[AsyncSession, WebhookEvent], Awaitable[None]]


async def _default_handler(session: AsyncSession, event: WebhookEvent) -> None:
    await pipeline_orchestrator.handle_webhook_event(session, event)
    event.processing_status = WebhookProcessingStatus.PROCESSED.value
    logger.info(
        "webhook_event processed",
        extra={"webhook_event_id": str(event.id), "event_type": event.event_type},
    )


async def poll_once(session: AsyncSession, handler: EventHandler = _default_handler) -> int:
    """Claim up to BATCH_SIZE pending events and hand them to `handler`. Returns count claimed."""
    result = await session.execute(
        select(WebhookEvent)
        .where(WebhookEvent.processing_status == WebhookProcessingStatus.PENDING.value)
        .order_by(WebhookEvent.razorpay_created_at, WebhookEvent.sequence_id)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    events = list(result.scalars())
    for event in events:
        event.processing_status = WebhookProcessingStatus.PROCESSING.value
        await session.flush()
        try:
            await handler(session, event)
        except Exception:  # noqa: BLE001 — a bad event must not kill the worker loop
            logger.exception("webhook_event processing failed", extra={"webhook_event_id": str(event.id)})
            event.processing_status = WebhookProcessingStatus.FAILED.value
    await session.commit()
    return len(events)


async def run_forever(stop_event: asyncio.Event | None = None) -> None:
    session_factory = get_sessionmaker()
    stop_event = stop_event or asyncio.Event()
    logger.info("background worker started")
    while not stop_event.is_set():
        try:
            async with session_factory() as session:
                await poll_once(session)
                dispatched = await execution_service.dispatch_due_scheduled_actions(session)
                await session.commit()
                if dispatched:
                    logger.info("dispatched due scheduled actions", extra={"count": dispatched})
        except Exception:  # noqa: BLE001 — keep polling even if a whole batch attempt fails
            logger.exception("background worker poll iteration failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
        except TimeoutError:
            pass
