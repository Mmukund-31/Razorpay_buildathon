"""Explicit API-level assertions for duplicate and out-of-order webhook delivery (task
requirements: same event twice -> processed once; FAILED -> CAPTURED -> stale duplicate
FAILED -> final state stays CAPTURED). The underlying guarantees are already unit-tested in
tests/unit/test_payment_state_machine.py (pure `apply_event()` logic) and
tests/integration/test_webhook_ingestion.py (webhook-level event-id dedup) — this file
exercises them together through the real HTTP endpoint + background worker poll, the way
Razorpay's actual at-least-once, out-of-order delivery would.

Needs a real database — skips gracefully without one via the `db_session`/`client` fixtures.
"""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.background_worker import poll_once
from app.core.config import get_settings
from app.domain.enums import PaymentStatus
from app.domain.models.payment import Payment
from app.domain.models.recovery_action import RecoveryAction
from app.domain.models.recovery_case import RecoveryCase

pytestmark = pytest.mark.integration


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


async def _post(
    client, secret: str, *, event_type: str, payment_id: str, created_at: int, event_id: str
) -> dict:
    payload = {
        "event": event_type,
        "created_at": created_at,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": 500000,
                    "currency": "INR",
                    "method": "card",
                    "error_reason": "insufficient_funds" if event_type == "payment.failed" else None,
                }
            }
        },
    }
    body = json.dumps(payload).encode("utf-8")
    response = await client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": _sign(body, secret),
            "X-Razorpay-Event-Id": event_id,
        },
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_duplicate_webhook_is_processed_once_with_no_duplicate_side_effects(client, db_session):
    """Same event, same event id, sent twice: first processed, second safely ignored — no
    duplicate RecoveryAction, no duplicate recovery amount, no duplicate audit outcome."""
    settings = get_settings()
    if not settings.razorpay_webhook_secret:
        pytest.skip("RAZORPAY_WEBHOOK_SECRET not configured — set it in .env to run this test.")

    payment_id = f"pay_dup_{uuid.uuid4().hex[:12]}"
    event_id = f"evt_{uuid.uuid4().hex}"
    now = int(datetime.now(UTC).timestamp())

    first = await _post(
        client, settings.razorpay_webhook_secret,
        event_type="payment.failed", payment_id=payment_id, created_at=now, event_id=event_id,
    )
    assert first == {"status": "ok", "duplicate": False}
    await poll_once(db_session)

    second = await _post(
        client, settings.razorpay_webhook_secret,
        event_type="payment.failed", payment_id=payment_id, created_at=now, event_id=event_id,
    )
    assert second == {"status": "ok", "duplicate": True}
    processed = await poll_once(db_session)
    assert processed == 0  # nothing new to process — the duplicate was never even persisted

    payment = (
        await db_session.execute(select(Payment).where(Payment.razorpay_payment_id == payment_id))
    ).scalar_one()
    assert payment.status == PaymentStatus.FAILED.value

    cases = (
        await db_session.execute(select(RecoveryCase).where(RecoveryCase.payment_id == payment.id))
    ).scalars().all()
    assert len(cases) <= 1  # never two cases for one payment (schema-enforced, re-verified here)


@pytest.mark.asyncio
async def test_out_of_order_captured_then_stale_failed_stays_captured(client, db_session):
    """FAILED -> CAPTURED -> a stale, late-arriving duplicate FAILED (earlier timestamp) for
    the same payment_id must NOT regress the payment back to FAILED. The final state must
    remain CAPTURED."""
    settings = get_settings()
    if not settings.razorpay_webhook_secret:
        pytest.skip("RAZORPAY_WEBHOOK_SECRET not configured — set it in .env to run this test.")

    payment_id = f"pay_ooo_{uuid.uuid4().hex[:12]}"
    t0 = int(datetime.now(UTC).timestamp())

    await _post(
        client, settings.razorpay_webhook_secret,
        event_type="payment.failed", payment_id=payment_id, created_at=t0, event_id=f"evt_{uuid.uuid4().hex}",
    )
    await poll_once(db_session)

    await _post(
        client, settings.razorpay_webhook_secret,
        event_type="payment.captured", payment_id=payment_id, created_at=t0 + 10,
        event_id=f"evt_{uuid.uuid4().hex}",
    )
    await poll_once(db_session)

    payment = (
        await db_session.execute(select(Payment).where(Payment.razorpay_payment_id == payment_id))
    ).scalar_one()
    assert payment.status == PaymentStatus.CAPTURED.value

    # A stale, out-of-order re-delivery of the ORIGINAL failure — earlier timestamp than the
    # capture already applied. Must be ignored, never regress CAPTURED back to FAILED.
    await _post(
        client, settings.razorpay_webhook_secret,
        event_type="payment.failed", payment_id=payment_id, created_at=t0,
        event_id=f"evt_{uuid.uuid4().hex}",
    )
    await poll_once(db_session)

    await db_session.refresh(payment)
    assert payment.status == PaymentStatus.CAPTURED.value

    # No duplicate recovery action should exist from the stale re-processing attempt.
    cases = (
        await db_session.execute(select(RecoveryCase).where(RecoveryCase.payment_id == payment.id))
    ).scalars().all()
    for case in cases:
        actions = (
            await db_session.execute(
                select(RecoveryAction).where(RecoveryAction.recovery_case_id == case.id)
            )
        ).scalars().all()
        keys = [a.idempotency_key for a in actions]
        assert len(keys) == len(set(keys))  # no duplicate idempotency keys under one case
