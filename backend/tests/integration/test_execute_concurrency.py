"""Race-condition test: two simultaneous POST /recovery-cases/{id}/execute requests for the
SAME case must produce exactly one RecoveryAction — never two, never a duplicate Payment
Link. Exercises the real safety mechanism (recovery_case_service.transition()'s optimistic
lock on `recovery_cases.version`), not a new one added for this test: the loser's
BEGIN_EXECUTION trigger loses the `WHERE id=:id AND version=:expected` race, sees its case
object still at POLICY_APPROVED (never refreshed), and execution_service.execute() returns
immediately without ever reaching the RecoveryAction insert — so the idempotency-key UNIQUE
constraint is defense-in-depth here, not the primary guard.

Needs a real database — skips gracefully without one via the `db_session`/`client` fixtures.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.domain.enums import ActionType, PaymentStatus, RecoveryCaseStatus
from app.domain.models.payment import Payment
from app.domain.models.policy_evaluation import PolicyEvaluation
from app.domain.models.recovery_action import RecoveryAction
from app.domain.models.recovery_case import RecoveryCase
from app.domain.models.recovery_opportunity import RecoveryOpportunity
from app.integrations.gateway_interface import PaymentLinkGateway
from app.integrations.simulator_gateway import SimulatorPaymentLinkAdapter

pytestmark = pytest.mark.integration


class _CountingPaymentLinkGateway(PaymentLinkGateway):
    """Wraps the real (simulator) gateway and counts every call — used to prove concurrent or
    repeated execute() calls never create more than one actual Payment Link, not just one
    RecoveryAction row."""

    def __init__(self) -> None:
        self.call_count = 0
        self._delegate = SimulatorPaymentLinkAdapter()

    async def create_payment_link(self, **kwargs) -> dict:
        self.call_count += 1
        return await self._delegate.create_payment_link(**kwargs)


async def _make_policy_approved_case(db_session) -> RecoveryCase:
    payment = Payment(
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:14]}",
        amount=999900,
        currency="INR",
        status=PaymentStatus.FAILED.value,
        is_terminal=False,
    )
    db_session.add(payment)
    await db_session.flush()

    opportunity = RecoveryOpportunity(
        payment_id=payment.id,
        opportunity_type="ONE_TIME_PAYMENT_FAILURE",
        amount_at_risk=payment.amount,
        currency=payment.currency,
        detected_at=datetime.now(UTC),
        status="CONVERTED_TO_CASE",
    )
    db_session.add(opportunity)
    await db_session.flush()

    case = RecoveryCase(
        opportunity_id=opportunity.id,
        payment_id=payment.id,
        status=RecoveryCaseStatus.POLICY_APPROVED.value,
        amount=payment.amount,
        currency=payment.currency,
        selected_action=ActionType.SMART_RETRY.value,
        version=0,
    )
    db_session.add(case)
    await db_session.flush()

    policy_evaluation = PolicyEvaluation(
        recovery_case_id=case.id,
        candidate_action=ActionType.SMART_RETRY.value,
        allowed=True,
        reason_codes=[],
        policy_version="v1",
    )
    db_session.add(policy_evaluation)
    await db_session.commit()
    return case


@pytest.mark.asyncio
async def test_two_simultaneous_execute_requests_create_exactly_one_action(client, db_session):
    case = await _make_policy_approved_case(db_session)

    responses = await asyncio.gather(
        client.post(f"/api/recovery-cases/{case.id}/execute", json={"consent_recorded": False}),
        client.post(f"/api/recovery-cases/{case.id}/execute", json={"consent_recorded": False}),
        return_exceptions=True,
    )

    for response in responses:
        assert not isinstance(response, Exception), f"a concurrent execute() request raised: {response}"
        # Depending on exact timing, the loser either reaches execute() and gets the
        # idempotent-no-op case back (200), or its own `_get_case_or_404` fetch happens after
        # the winner's full commit and is rejected upstream by the status guard (409,
        # CASE_NOT_READY_FOR_EXECUTION, since the case is no longer POLICY_APPROVED/SCHEDULED
        # by then) — both are safe, correct outcomes. What must NEVER happen is a 500.
        assert response.status_code in (200, 409), response.text
    assert any(r.status_code == 200 for r in responses), "at least one request must succeed"

    actions = (
        await db_session.execute(
            select(RecoveryAction).where(RecoveryAction.recovery_case_id == case.id)
        )
    ).scalars().all()
    assert len(actions) == 1, f"expected exactly one RecoveryAction, got {len(actions)}"
    assert actions[0].channel == "payment_link"

    await db_session.refresh(case)
    assert case.status == RecoveryCaseStatus.EXECUTING.value
    assert case.version == 1  # exactly one successful transition, not two


@pytest.mark.asyncio
async def test_two_simultaneous_execute_requests_create_exactly_one_payment_link(
    client, db_session, monkeypatch
):
    """Same race as above, but asserts the thing that actually matters financially: exactly
    one real Payment Link gets created at Razorpay, not just exactly one RecoveryAction row.
    A duplicate Payment Link would mean two live links a customer could pay through for the
    same debt."""
    case = await _make_policy_approved_case(db_session)
    gateway = _CountingPaymentLinkGateway()
    monkeypatch.setattr("app.services.execution_service.get_payment_link_gateway", lambda: gateway)

    responses = await asyncio.gather(
        client.post(f"/api/recovery-cases/{case.id}/execute", json={"consent_recorded": False}),
        client.post(f"/api/recovery-cases/{case.id}/execute", json={"consent_recorded": False}),
        return_exceptions=True,
    )

    for response in responses:
        assert not isinstance(response, Exception), f"a concurrent execute() request raised: {response}"
        assert response.status_code in (200, 409), response.text

    assert gateway.call_count == 1, f"expected exactly one Payment Link created, got {gateway.call_count}"


@pytest.mark.asyncio
async def test_re_executing_an_already_executing_case_creates_no_second_payment_link(
    client, db_session, monkeypatch
):
    """Sequential (not racing) re-invocation: once a case has moved to EXECUTING, calling
    /execute again must be rejected outright — never dispatch a second Payment Link for the
    same case."""
    case = await _make_policy_approved_case(db_session)
    gateway = _CountingPaymentLinkGateway()
    monkeypatch.setattr("app.services.execution_service.get_payment_link_gateway", lambda: gateway)

    first = await client.post(f"/api/recovery-cases/{case.id}/execute", json={"consent_recorded": False})
    assert first.status_code == 200
    assert gateway.call_count == 1

    second = await client.post(f"/api/recovery-cases/{case.id}/execute", json={"consent_recorded": False})
    assert second.status_code == 409
    assert second.json()["code"] == "CASE_NOT_READY_FOR_EXECUTION"
    assert gateway.call_count == 1  # unchanged — no second Payment Link

    actions = (
        await db_session.execute(select(RecoveryAction).where(RecoveryAction.recovery_case_id == case.id))
    ).scalars().all()
    assert len(actions) == 1
