"""End-to-end: a real `payment.failed` webhook -> an executed SMART_RETRY (a real Payment
Link, via the simulator adapter since no live Razorpay credentials are configured in this
environment) -> a `payment_link.paid` webhook for a DIFFERENT razorpay_payment_id carrying
the correlation reference_id -> the case resolves to SUCCEEDED with the correct
actual_recovered_amount -> replaying the same captured webhook is a safe no-op. This is the
P0 payment-link-recovery gap, exercised through the real HTTP + background-worker-poll path,
not just the outcome_service unit-level tests in test_outcome_service.py.

Needs a real database (webhook persistence + the pipeline's DB writes) — skips gracefully
without one via the `db_session`/`client` fixtures (see tests/conftest.py).
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
from app.domain.enums import PaymentStatus, RecoveryActionStatus, RecoveryCaseStatus
from app.domain.models.payment import Payment
from app.domain.models.recovery_action import RecoveryAction
from app.domain.models.recovery_case import RecoveryCase
from app.domain.recovery_action_reference import build_reference_id

pytestmark = pytest.mark.integration


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _webhook_body(*, event_type: str, payload: dict) -> bytes:
    envelope = {"event": event_type, "created_at": int(datetime.now(UTC).timestamp()), "payload": payload}
    return json.dumps(envelope).encode("utf-8")


async def _post_webhook(client, *, event_type: str, payload: dict, event_id: str | None = None) -> dict:
    settings = get_settings()
    body = _webhook_body(event_type=event_type, payload=payload)
    response = await client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": _sign(body, settings.razorpay_webhook_secret),
            "X-Razorpay-Event-Id": event_id or f"evt_{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_payment_link_recovery_resolves_end_to_end(client, db_session):
    settings = get_settings()
    if not settings.razorpay_webhook_secret:
        pytest.skip("RAZORPAY_WEBHOOK_SECRET not configured — set it in .env to run this test.")

    original_payment_id = f"pay_orig_{uuid.uuid4().hex[:12]}"
    amount = 1499900

    # 1. A real payment.failed webhook — this drives the full autonomous pipeline
    #    (state reconstruction -> revenue signal -> case -> eligibility -> analysis ->
    #    policy -> execution) via the background worker, exactly as production would.
    await _post_webhook(
        client,
        event_type="payment.failed",
        payload={
            "payment": {
                "entity": {
                    "id": original_payment_id,
                    "order_id": f"order_{uuid.uuid4().hex[:10]}",
                    "amount": amount,
                    "currency": "INR",
                    "method": "upi",
                    "email": "customer@example.com",
                    "contact": "+919999999999",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Insufficient funds in account",
                    "error_source": "bank",
                    "error_step": "payment_authorization",
                    "error_reason": "insufficient_funds",
                }
            }
        },
    )
    processed = await poll_once(db_session)
    assert processed >= 1

    original_payment = (
        await db_session.execute(select(Payment).where(Payment.razorpay_payment_id == original_payment_id))
    ).scalar_one()
    assert original_payment.status == PaymentStatus.FAILED.value

    case = (
        await db_session.execute(select(RecoveryCase).where(RecoveryCase.payment_id == original_payment.id))
    ).scalar_one_or_none()
    if case is None:
        pytest.skip(
            "No recovery case was created for this synthetic failure (e.g. below the "
            "revenue-at-risk floor, or the AI/ML pipeline abstained without live credentials "
            "configured) — nothing to correlate. See docs/limitations.md."
        )

    action = (
        await db_session.execute(
            select(RecoveryAction)
            .where(RecoveryAction.recovery_case_id == case.id)
            .where(RecoveryAction.status == RecoveryActionStatus.SUCCEEDED.value)
        )
    ).scalars().first()
    if action is None or not action.external_reference:
        pytest.skip(
            "No SMART_RETRY/DELAYED_RETRY/CUSTOMER_ACTION_REQUEST action executed for this "
            "case (e.g. policy rejected it, or the case is still awaiting consent) — nothing "
            "to correlate."
        )

    reference_id = build_reference_id(action.id)
    new_payment_id = f"pay_new_{uuid.uuid4().hex[:12]}"

    # 2. The customer pays via the recovery Payment Link -> Razorpay fires payment_link.paid
    #    with the SAME reference_id RecoveryOS set at creation time, for a NEW payment_id.
    link_payload = {
        "payment_link": {
            "entity": {"id": action.external_reference, "reference_id": reference_id, "notes": {}}
        },
        "payment": {
            "entity": {
                "id": new_payment_id,
                "order_id": f"order_{uuid.uuid4().hex[:10]}",
                "amount": amount,
                "currency": "INR",
                "method": "upi",
            }
        },
    }
    await _post_webhook(client, event_type="payment_link.paid", payload=link_payload)
    await poll_once(db_session)

    await db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.SUCCEEDED.value
    assert case.actual_recovered_amount == amount
    new_payment = (
        await db_session.execute(select(Payment).where(Payment.razorpay_payment_id == new_payment_id))
    ).scalar_one()
    assert case.resolved_payment_id == new_payment.id
    assert case.payment_id == original_payment.id  # the original failed payment id is untouched

    # 3. Replaying the exact same payment_link.paid content under a DIFFERENT event id
    #    (simulating the payment gateway itself re-notifying, rather than Razorpay's exact
    #    at-least-once redelivery — already covered by test_webhook_ingestion.py's
    #    same-event-id dedup) must still be a safe no-op: this exercises reconcile_outcome's
    #    OWN idempotency guard, not the webhook-layer event-id dedup.
    await _post_webhook(client, event_type="payment_link.paid", payload=link_payload)
    await poll_once(db_session)

    await db_session.refresh(case)
    assert case.actual_recovered_amount == amount  # unchanged, not doubled
    assert case.status == RecoveryCaseStatus.SUCCEEDED.value
