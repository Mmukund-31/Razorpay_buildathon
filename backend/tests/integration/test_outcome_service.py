"""Exercises app/services/outcome_service.py against a real database: the same-payment-id
path (unchanged UPI-retry behavior), the NEW payment-link-correlation path this module exists
to fix, idempotent double-reconciliation, already-terminal-case safety, a currency mismatch
guard, and pending-action cancellation. Needs a real database — skips gracefully without one
via the `db_session` fixture (see tests/conftest.py).
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.enums import ActionType, PaymentStatus, RecoveryActionStatus, RecoveryCaseStatus
from app.domain.models.payment import Payment
from app.domain.models.policy_evaluation import PolicyEvaluation
from app.domain.models.recovery_action import RecoveryAction
from app.domain.models.recovery_case import RecoveryCase
from app.domain.models.recovery_opportunity import RecoveryOpportunity
from app.services import outcome_service

pytestmark = pytest.mark.integration


async def _make_payment(db_session, *, status: str, amount: int = 1499900, currency: str = "INR") -> Payment:
    payment = Payment(
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:14]}",
        amount=amount,
        currency=currency,
        status=status,
        is_terminal=status in (PaymentStatus.CAPTURED.value, PaymentStatus.REFUNDED.value),
    )
    db_session.add(payment)
    await db_session.flush()
    return payment


async def _make_case_with_action(
    db_session, *, original_payment: Payment, status: str = RecoveryCaseStatus.EXECUTING.value
) -> tuple[RecoveryCase, RecoveryAction]:
    opportunity = RecoveryOpportunity(
        payment_id=original_payment.id,
        opportunity_type="ONE_TIME_PAYMENT_FAILURE",
        amount_at_risk=original_payment.amount,
        currency=original_payment.currency,
        detected_at=datetime.now(UTC),
        status="CONVERTED_TO_CASE",
    )
    db_session.add(opportunity)
    await db_session.flush()

    case = RecoveryCase(
        opportunity_id=opportunity.id,
        payment_id=original_payment.id,
        status=status,
        amount=original_payment.amount,
        currency=original_payment.currency,
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
    await db_session.flush()

    action = RecoveryAction(
        recovery_case_id=case.id,
        action_type=ActionType.SMART_RETRY.value,
        status=RecoveryActionStatus.SUCCEEDED.value,
        idempotency_key=f"{case.id}:{ActionType.SMART_RETRY.value}:0",
        external_reference=f"plink_{uuid.uuid4().hex[:14]}",
        policy_evaluation_id=policy_evaluation.id,
    )
    db_session.add(action)
    await db_session.flush()
    return case, action


@pytest.mark.asyncio
async def test_same_payment_id_path_resolves_case_and_records_actual_amount(db_session):
    """The verified UPI wrong-PIN-then-retry quirk: the captured payment IS the case's
    original payment_id — no correlation needed, and this path must keep working exactly as
    it did before outcome_service existed."""
    original = await _make_payment(db_session, status=PaymentStatus.CAPTURED.value)
    case, _action = await _make_case_with_action(db_session, original_payment=original)

    resolved = await outcome_service.reconcile_outcome(db_session, original, uuid.uuid4())

    assert resolved is not None
    assert resolved.id == case.id
    assert resolved.status == RecoveryCaseStatus.SUCCEEDED.value
    assert resolved.actual_recovered_amount == original.amount
    assert resolved.resolved_payment_id == original.id


@pytest.mark.asyncio
async def test_payment_link_correlation_resolves_case_via_recovery_action_id(db_session):
    """The P0 fix: a captured payment with a DIFFERENT razorpay_payment_id than the case's
    original (failed) payment, correlated purely via `payments.recovery_action_id` (resolved
    from the Payment Link's echoed reference_id at reconstruction time)."""
    original = await _make_payment(db_session, status=PaymentStatus.FAILED.value)
    case, action = await _make_case_with_action(db_session, original_payment=original)

    new_payment = await _make_payment(db_session, status=PaymentStatus.CAPTURED.value, amount=original.amount)
    new_payment.recovery_action_id = action.id
    await db_session.flush()

    resolved = await outcome_service.reconcile_outcome(db_session, new_payment, uuid.uuid4())

    assert resolved is not None
    assert resolved.id == case.id
    assert resolved.status == RecoveryCaseStatus.SUCCEEDED.value
    assert resolved.actual_recovered_amount == new_payment.amount
    assert resolved.resolved_payment_id == new_payment.id
    # The original failed payment's id is untouched — it is NOT what resolved the case.
    assert resolved.payment_id == original.id
    assert resolved.payment_id != resolved.resolved_payment_id


@pytest.mark.asyncio
async def test_idempotent_double_reconciliation_does_not_change_amount(db_session):
    """Five re-deliveries of the same captured signal must still leave
    actual_recovered_amount exactly equal to the true amount — never additive."""
    original = await _make_payment(db_session, status=PaymentStatus.FAILED.value)
    case, action = await _make_case_with_action(db_session, original_payment=original)
    new_payment = await _make_payment(db_session, status=PaymentStatus.CAPTURED.value, amount=original.amount)
    new_payment.recovery_action_id = action.id
    await db_session.flush()

    for _ in range(5):
        resolved = await outcome_service.reconcile_outcome(db_session, new_payment, uuid.uuid4())
        assert resolved is not None
        assert resolved.actual_recovered_amount == original.amount

    await db_session.refresh(case)
    assert case.actual_recovered_amount == original.amount


@pytest.mark.asyncio
async def test_already_terminal_case_found_via_correlation_is_not_regressed(db_session):
    """`get_live_case_for_payment` already excludes terminal cases by construction (the
    partial-unique-index definition of "live"), so the same-payment-id path can never re-find
    a SUCCEEDED case. The recovery_action_id correlation path has no such filter — it fetches
    the case unconditionally — so THIS is the path that must defend against re-resolving (or
    worse, re-writing the amount on) a case a duplicate/re-delivered webhook already closed."""
    original = await _make_payment(db_session, status=PaymentStatus.FAILED.value)
    case, action = await _make_case_with_action(
        db_session, original_payment=original, status=RecoveryCaseStatus.SUCCEEDED.value
    )
    case.actual_recovered_amount = case.amount
    await db_session.flush()

    new_payment = await _make_payment(db_session, status=PaymentStatus.CAPTURED.value, amount=original.amount)
    new_payment.recovery_action_id = action.id
    await db_session.flush()

    resolved = await outcome_service.reconcile_outcome(db_session, new_payment, uuid.uuid4())

    assert resolved is not None
    assert resolved.status == RecoveryCaseStatus.SUCCEEDED.value
    assert resolved.actual_recovered_amount == case.amount
    assert resolved.resolved_payment_id != new_payment.id  # untouched — the case already had one


@pytest.mark.asyncio
async def test_currency_mismatch_is_logged_and_does_not_resolve(db_session):
    original = await _make_payment(db_session, status=PaymentStatus.FAILED.value, currency="INR")
    case, action = await _make_case_with_action(db_session, original_payment=original)
    new_payment = await _make_payment(
        db_session, status=PaymentStatus.CAPTURED.value, amount=original.amount, currency="USD"
    )
    new_payment.recovery_action_id = action.id
    await db_session.flush()

    resolved = await outcome_service.reconcile_outcome(db_session, new_payment, uuid.uuid4())

    assert resolved is not None
    assert resolved.status == RecoveryCaseStatus.EXECUTING.value
    assert resolved.actual_recovered_amount is None


@pytest.mark.asyncio
async def test_pending_actions_cancelled_but_succeeded_actions_left_alone(db_session):
    original = await _make_payment(db_session, status=PaymentStatus.FAILED.value)
    case, succeeded_action = await _make_case_with_action(db_session, original_payment=original)

    pending_policy = PolicyEvaluation(
        recovery_case_id=case.id,
        candidate_action=ActionType.DELAYED_RETRY.value,
        allowed=True,
        reason_codes=[],
        policy_version="v1",
    )
    db_session.add(pending_policy)
    await db_session.flush()
    pending_action = RecoveryAction(
        recovery_case_id=case.id,
        action_type=ActionType.DELAYED_RETRY.value,
        status=RecoveryActionStatus.PENDING.value,
        idempotency_key=f"{case.id}:{ActionType.DELAYED_RETRY.value}:1",
        policy_evaluation_id=pending_policy.id,
        scheduled_for=datetime.now(UTC),
    )
    db_session.add(pending_action)
    await db_session.flush()

    new_payment = await _make_payment(db_session, status=PaymentStatus.CAPTURED.value, amount=original.amount)
    new_payment.recovery_action_id = succeeded_action.id
    await db_session.flush()

    await outcome_service.reconcile_outcome(db_session, new_payment, uuid.uuid4())

    await db_session.refresh(pending_action)
    await db_session.refresh(succeeded_action)
    assert pending_action.status == RecoveryActionStatus.SKIPPED.value
    assert succeeded_action.status == RecoveryActionStatus.SUCCEEDED.value


@pytest.mark.asyncio
async def test_organic_payment_with_no_recovery_history_returns_none(db_session):
    payment = await _make_payment(db_session, status=PaymentStatus.CAPTURED.value)
    resolved = await outcome_service.reconcile_outcome(db_session, payment, uuid.uuid4())
    assert resolved is None
