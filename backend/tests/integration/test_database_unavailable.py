"""The `database_unavailable` failure-injection scenario (simulator/scenarios/scenario_definitions.py)
— deliberately NOT implemented as a webhook-event-batch scenario (see that module's docstring
for why: a database outage isn't a webhook payload shape, and injecting it by reaching into
internal state from the "pure data generation" scenario_runner.py would violate both that
module's own contract and ADR-004's "never a parallel fake path" rule). Proven here instead,
directly against the real endpoint via FastAPI's documented dependency-override mechanism
(`app.dependency_overrides[get_db]` — anticipated by app/db/session.py's own docstring).

Expected safe behavior: webhook ingestion returns a 5xx (never a fake 200 ack) and never
persists a webhook_events row when the database is unreachable.
"""

import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db

pytestmark = pytest.mark.integration


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


async def _broken_db() -> AsyncGenerator[AsyncSession, None]:
    raise OperationalError("connection failed", {}, Exception("simulated DB outage"))
    yield  # pragma: no cover — makes this an async generator; never reached


@pytest.mark.asyncio
async def test_webhook_ingestion_returns_5xx_not_a_fake_ack_when_db_unavailable(db_session):
    settings = get_settings()
    if not settings.razorpay_webhook_secret:
        pytest.skip("RAZORPAY_WEBHOOK_SECRET not configured — set it in .env to run this test.")

    from app.main import app

    payload = {"event": "payment.failed", "created_at": 1735689600, "payload": {}}
    body = json.dumps(payload).encode("utf-8")
    event_id = f"evt_dbdown_{uuid.uuid4().hex}"
    headers = {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": _sign(body, settings.razorpay_webhook_secret),
        "X-Razorpay-Event-Id": event_id,
    }

    # A local client with raise_app_exceptions=False, matching how a real ASGI server
    # (uvicorn, via Starlette's default exception middleware) actually behaves in
    # production — converts an unhandled exception into a real 500 response instead of
    # propagating it to the caller, which is httpx's ASGITransport test-only default.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    app.dependency_overrides[get_db] = _broken_db
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post("/api/webhooks/razorpay", content=body, headers=headers)
    finally:
        del app.dependency_overrides[get_db]

    assert response.status_code >= 500
    assert response.text != json.dumps({"status": "ok", "duplicate": False})  # never a fake ack

    from sqlalchemy import select

    from app.domain.models.webhook_event import WebhookEvent

    rows = (
        await db_session.execute(select(WebhookEvent).where(WebhookEvent.razorpay_event_id == event_id))
    ).scalars().all()
    assert len(rows) == 0  # nothing was persisted despite the outage
