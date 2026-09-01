"""The complete failed-payment -> RecoveryOS -> Payment Link -> payment -> webhook ->
outcome reconciliation -> actual recovered revenue -> audit ledger flow, driven entirely
through the real HTTP webhook endpoint (app/api/webhooks.py) and the real background worker
poll (app/core/background_worker.py) — the same two entry points Razorpay and the running
worker actually use in production. Nothing here is a stub any more (see
docs/final-readiness-report.md) — this test is the real proof the module docstring this file
used to carry promised, not a skip.

The only thing mocked is the ML predictor's *output*: a fixed, valid probability for
SMART_RETRY. Everything downstream of that boundary — optimizer expected-value math, the
policy gate, the executor, real (simulator-backed, since no live Razorpay credentials are
configured) Payment Link creation, webhook-triggered outcome reconciliation, and the audit
ledger — runs for real, unmocked. Pinning the ML output keeps this test deterministic without
making it hostage to what a specific trained model happens to score a specific synthetic
customer profile — that's a modeling question, already covered by docs/ml-evaluation.md's
dedicated benchmark, not what this test exists to prove.

  payment.failed webhook -> ingestion -> state reconstruction -> revenue signal detection
  -> recovery_opportunity -> recovery_case DETECTED -> ELIGIBLE -> ANALYZING
  -> ML prediction (fixed signal) -> ACTION_PROPOSED (SMART_RETRY)
  -> policy evaluates -> POLICY_APPROVED -> executor creates exactly one real Payment Link
  -> a later payment_link.paid webhook for a brand-new payment_id, correlated back via the
     link's reference_id -> outcome reconciliation -> case SUCCEEDED with the correct
     actual_recovered_amount (never just the expected amount)
  -> every hop traceable through the append-only audit_logs table.

See docs/track-alignment.md for how this maps to the Track 03 requirements and
docs/demo-script.md for how this same flow is demonstrated live.

Needs a real database — skips gracefully without one via the `db_session`/`client` fixtures.
"""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.agents import ml_predictor
from app.core.background_worker import poll_once
from app.core.config import get_settings
from app.domain.enums import ActionType, AuditEvent, PaymentStatus, RecoveryCaseStatus
from app.domain.models.audit_log import AuditLog
from app.domain.models.payment import Payment
from app.domain.models.recovery_action import RecoveryAction
from app.domain.models.recovery_case import RecoveryCase
from app.domain.models.recovery_opportunity import RecoveryOpportunity
from app.domain.recovery_action_reference import build_reference_id
from app.integrations.gateway_interface import PaymentLinkGateway
from app.integrations.simulator_gateway import SimulatorPaymentLinkAdapter

pytestmark = pytest.mark.integration

RECOVERY_AMOUNT_PAISE = 500_000  # ₹5,000 — well above every relevant threshold


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


async def _post_webhook(client, secret: str, payload: dict, *, event_id: str) -> dict:
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


class _CountingPaymentLinkGateway(PaymentLinkGateway):
    """Wraps the real (simulator) gateway and counts every call — the same duplicate-Payment-
    Link guard used in test_execute_concurrency.py, applied here to the full autonomous
    pipeline rather than a hand-built case."""

    def __init__(self) -> None:
        self.call_count = 0
        self._delegate = SimulatorPaymentLinkAdapter()

    async def create_payment_link(self, **kwargs) -> dict:
        self.call_count += 1
        return await self._delegate.create_payment_link(**kwargs)


def _fixed_ml_signal(only_action: ActionType, probability: float):
    async def _predict(action: ActionType, features: dict) -> ml_predictor.MLPrediction:
        if action != only_action:
            return ml_predictor.MLPrediction(
                is_valid=False,
                probability_of_recovery=None,
                model_version=None,
                latency_ms=0,
                error="not_the_test_candidate",
            )
        return ml_predictor.MLPrediction(
            is_valid=True,
            probability_of_recovery=probability,
            model_version="test-fixture-v1",
            latency_ms=1,
        )

    return _predict


@pytest.mark.asyncio
async def test_full_pipeline_payment_failure_to_recovery(client, db_session, monkeypatch):
    settings = get_settings()
    if not settings.razorpay_webhook_secret:
        pytest.skip("RAZORPAY_WEBHOOK_SECRET not configured — set it in .env to run this test.")

    gateway = _CountingPaymentLinkGateway()
    monkeypatch.setattr("app.services.execution_service.get_payment_link_gateway", lambda: gateway)
    monkeypatch.setattr("app.agents.ml_predictor.predict", _fixed_ml_signal(ActionType.SMART_RETRY, 0.75))

    original_payment_id = f"pay_e2e_{uuid.uuid4().hex[:12]}"
    now = int(datetime.now(UTC).timestamp())

    # 1. A real failed payment arrives, over the real, signature-verified webhook endpoint.
    failed_ack = await _post_webhook(
        client,
        settings.razorpay_webhook_secret,
        {
            "event": "payment.failed",
            "created_at": now,
            "payload": {
                "payment": {
                    "entity": {
                        "id": original_payment_id,
                        "amount": RECOVERY_AMOUNT_PAISE,
                        "currency": "INR",
                        "method": "upi",
                        "email": "e2e-test@example.com",
                        "contact": "+919999999999",
                        "error_reason": "insufficient_funds",
                    }
                }
            },
        },
        event_id=f"evt_{uuid.uuid4().hex}",
    )
    assert failed_ack == {"status": "ok", "duplicate": False}

    # 2. The background worker autonomously drives it end to end: state reconstruction ->
    #    revenue signal -> opportunity -> case -> eligibility -> ML/AI analysis -> optimizer
    #    -> policy -> execution -> a real (simulator-backed) Payment Link.
    processed = await poll_once(db_session)
    assert processed == 1

    original_payment = (
        await db_session.execute(select(Payment).where(Payment.razorpay_payment_id == original_payment_id))
    ).scalar_one()
    assert original_payment.status == PaymentStatus.FAILED.value  # never itself "retried"

    case = (
        await db_session.execute(select(RecoveryCase).where(RecoveryCase.payment_id == original_payment.id))
    ).scalar_one()
    assert case.status == RecoveryCaseStatus.EXECUTING.value
    assert case.selected_action == ActionType.SMART_RETRY.value

    action = (
        await db_session.execute(select(RecoveryAction).where(RecoveryAction.recovery_case_id == case.id))
    ).scalar_one()
    assert action.status == "SUCCEEDED"
    assert action.channel == "payment_link"
    assert action.external_reference is not None  # the (simulated) Razorpay Payment Link id
    assert gateway.call_count == 1  # exactly one Payment Link — never a duplicate

    # 3. The customer pays through that Payment Link — a brand-new razorpay_payment_id,
    #    correlated back to `action` via the link's reference_id, exactly as a real
    #    payment_link.paid delivery would arrive.
    recovered_payment_id = f"pay_e2e_recovered_{uuid.uuid4().hex[:8]}"
    paid_ack = await _post_webhook(
        client,
        settings.razorpay_webhook_secret,
        {
            "event": "payment_link.paid",
            "created_at": now + 3600,
            "payload": {
                "payment_link": {
                    "entity": {"id": action.external_reference, "reference_id": build_reference_id(action.id)}
                },
                "payment": {
                    "entity": {
                        "id": recovered_payment_id,
                        "amount": case.amount,
                        "currency": case.currency,
                        "method": "upi",
                    }
                },
            },
        },
        event_id=f"evt_{uuid.uuid4().hex}",
    )
    assert paid_ack == {"status": "ok", "duplicate": False}

    # 4. The background worker reconciles the outcome.
    processed = await poll_once(db_session)
    assert processed == 1

    await db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.SUCCEEDED.value
    # ACTUAL recovered revenue, not the merely-expected amount computed back in step 2 — the
    # whole point of the outcome-reconciliation loop this test exists to prove closed.
    assert case.actual_recovered_amount == RECOVERY_AMOUNT_PAISE

    recovered_payment = (
        await db_session.execute(select(Payment).where(Payment.razorpay_payment_id == recovered_payment_id))
    ).scalar_one()
    assert case.resolved_payment_id == recovered_payment.id
    # The complete correlation chain: original_payment -> recovery_case -> recovery_action ->
    # payment_link -> recovered_payment, intact and independently queryable from either end.
    assert recovered_payment.recovery_action_id == action.id

    # 5. Every hop is traceable through the append-only audit ledger, keyed off the
    #    opportunity/case/action's own ids — not just asserted to exist somewhere, but
    #    queryable back from the actual recovered-revenue event to the recovery action that
    #    earned it.
    opportunity = (
        await db_session.execute(
            select(RecoveryOpportunity).where(RecoveryOpportunity.payment_id == original_payment.id)
        )
    ).scalar_one()
    opportunity_events = (
        await db_session.execute(
            select(AuditLog.event).where(
                AuditLog.entity_type == "recovery_opportunity", AuditLog.entity_id == opportunity.id
            )
        )
    ).scalars().all()
    assert AuditEvent.REVENUE_DETECTED.value in opportunity_events

    case_events = (
        await db_session.execute(
            select(AuditLog.event).where(
                AuditLog.entity_type == "recovery_case", AuditLog.entity_id == case.id
            )
        )
    ).scalars().all()
    assert AuditEvent.ML_SCORED.value in case_events
    assert AuditEvent.ACTION_OPTIMIZED.value in case_events
    assert AuditEvent.POLICY_APPROVED.value in case_events
    assert AuditEvent.PAYMENT_RECOVERED.value in case_events

    action_events = (
        await db_session.execute(
            select(AuditLog.event).where(
                AuditLog.entity_type == "recovery_action", AuditLog.entity_id == action.id
            )
        )
    ).scalars().all()
    assert AuditEvent.ACTION_EXECUTED.value in action_events
