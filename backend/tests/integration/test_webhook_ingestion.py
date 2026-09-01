"""Exercises POST /api/webhooks/razorpay end-to-end against a real database: bad signature ->
400, good signature -> 200 + persisted row, duplicate event id -> 200 + no second row. Skips
gracefully if Postgres isn't reachable (client still works without DB, but assertions here
need to read back persisted rows, hence `db_session`).
"""

import hashlib
import hmac
import json
import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.domain.models.webhook_event import WebhookEvent

pytestmark = pytest.mark.integration


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_invalid_signature_returns_400(client, db_session):
    payload = {"event": "payment.failed", "created_at": 1735689600}
    body = json.dumps(payload).encode("utf-8")

    response = await client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": "not-a-valid-signature",
            "X-Razorpay-Event-Id": f"evt_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 400
    body_json = response.json()
    assert set(body_json.keys()) == {"code", "message", "request_id"}
    assert body_json["code"] == "INVALID_WEBHOOK_SIGNATURE"


@pytest.mark.asyncio
async def test_valid_signature_persists_event_and_duplicate_is_idempotent(client, db_session):
    settings = get_settings()
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = {"event": "payment.failed", "created_at": 1735689600, "payload": {}}
    body = json.dumps(payload).encode("utf-8")
    signature = _sign(body, settings.razorpay_webhook_secret or "test-secret-for-ci")

    headers = {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": event_id,
    }

    # This test signs with the CONFIGURED secret, so it only proves something if that secret
    # is non-empty. With the default empty secret, verify_signature() always returns False —
    # which is correct, safe behavior (see webhook_verifier.py), so we skip rather than assert
    # a false positive.
    if not settings.razorpay_webhook_secret:
        pytest.skip("RAZORPAY_WEBHOOK_SECRET not configured — set it in .env to run this test.")

    first = await client.post("/api/webhooks/razorpay", content=body, headers=headers)
    assert first.status_code == 200
    assert first.json() == {"status": "ok", "duplicate": False}

    second = await client.post("/api/webhooks/razorpay", content=body, headers=headers)
    assert second.status_code == 200
    assert second.json() == {"status": "ok", "duplicate": True}

    rows = (
        await db_session.execute(select(WebhookEvent).where(WebhookEvent.razorpay_event_id == event_id))
    ).scalars().all()
    assert len(rows) == 1
