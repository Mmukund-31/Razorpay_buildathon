from datetime import UTC, datetime, timedelta

import pytest

from app.domain.enums import ActionType, PolicyReasonCode
from app.domain.schemas.policy_decision import PolicyDecision
from app.policies.policy_engine import PolicyEngine
from app.policies.rules import PolicyContext

pytestmark = pytest.mark.unit

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_context(**overrides) -> PolicyContext:
    defaults = dict(
        already_recovered=False,
        attempt_count=0,
        max_attempts=3,
        recovery_window_expires_at=NOW + timedelta(hours=1),
        now=NOW,
        customer_opted_out=False,
        candidate_action=ActionType.SMART_RETRY,
        opportunity_type="ONE_TIME_PAYMENT_FAILURE",
        expected_value=500.0,
        min_expected_value=100.0,
        confidence=0.8,
        min_confidence=0.55,
        consent_recorded=True,
    )
    defaults.update(overrides)
    return PolicyContext(**defaults)


def test_allows_a_clean_candidate():
    decision = PolicyEngine().evaluate(make_context())
    assert isinstance(decision, PolicyDecision)
    assert decision.allowed is True
    assert decision.reason_codes == []
    assert decision.policy_version == "policy-v1"


def test_rejects_already_recovered():
    decision = PolicyEngine().evaluate(make_context(already_recovered=True))
    assert not decision.allowed
    assert PolicyReasonCode.ALREADY_RECOVERED in decision.reason_codes


def test_rejects_retry_limit_reached():
    decision = PolicyEngine().evaluate(make_context(attempt_count=3, max_attempts=3))
    assert not decision.allowed
    assert PolicyReasonCode.RETRY_LIMIT_REACHED in decision.reason_codes


def test_rejects_recovery_window_expired():
    decision = PolicyEngine().evaluate(
        make_context(recovery_window_expires_at=NOW - timedelta(hours=1))
    )
    assert not decision.allowed
    assert PolicyReasonCode.RECOVERY_WINDOW_EXPIRED in decision.reason_codes


def test_rejects_customer_opted_out():
    decision = PolicyEngine().evaluate(make_context(customer_opted_out=True))
    assert not decision.allowed
    assert PolicyReasonCode.CUSTOMER_OPTED_OUT in decision.reason_codes


def test_rejects_expected_value_below_min():
    decision = PolicyEngine().evaluate(make_context(expected_value=10.0, min_expected_value=100.0))
    assert not decision.allowed
    assert PolicyReasonCode.EXPECTED_VALUE_BELOW_MIN in decision.reason_codes


def test_rejects_confidence_below_min():
    decision = PolicyEngine().evaluate(make_context(confidence=0.2, min_confidence=0.55))
    assert not decision.allowed
    assert PolicyReasonCode.CONFIDENCE_BELOW_MIN in decision.reason_codes


def test_hinglish_voice_requires_consent():
    decision = PolicyEngine().evaluate(
        make_context(candidate_action=ActionType.HINGLISH_VOICE, consent_recorded=False)
    )
    assert not decision.allowed
    assert PolicyReasonCode.CONSENT_REQUIRED_BUT_MISSING in decision.reason_codes


def test_hinglish_voice_allowed_with_consent():
    decision = PolicyEngine().evaluate(
        make_context(candidate_action=ActionType.HINGLISH_VOICE, consent_recorded=True)
    )
    assert decision.allowed


def test_collects_every_failing_reason_not_just_the_first():
    decision = PolicyEngine().evaluate(
        make_context(already_recovered=True, customer_opted_out=True, attempt_count=5, max_attempts=3)
    )
    assert not decision.allowed
    assert {
        PolicyReasonCode.ALREADY_RECOVERED,
        PolicyReasonCode.CUSTOMER_OPTED_OUT,
        PolicyReasonCode.RETRY_LIMIT_REACHED,
    } <= set(decision.reason_codes)


def test_bad_ai_demo_scenario_max_retries_blocks_smart_retry():
    """The product spec's own 'bad AI demo': AI recommends SMART_RETRY, policy rejects it
    because the retry limit was already reached — a real policy decision, not a scripted one.
    """
    decision = PolicyEngine().evaluate(
        make_context(candidate_action=ActionType.SMART_RETRY, attempt_count=3, max_attempts=3)
    )
    assert not decision.allowed
    assert decision.reason_codes == [PolicyReasonCode.RETRY_LIMIT_REACHED]
