import pytest

from app.domain.enums import ActionType, RecoveryCaseStatus
from app.domain.recovery_case_state_machine import CaseTrigger, RecoveryCaseSnapshot, apply_trigger

pytestmark = pytest.mark.unit


def snapshot(
    status: RecoveryCaseStatus, *, attempt_count=0, max_attempts=3, version=0
) -> RecoveryCaseSnapshot:
    return RecoveryCaseSnapshot(
        status=status, attempt_count=attempt_count, max_attempts=max_attempts, version=version
    )


def test_full_happy_path_detected_to_succeeded():
    steps = [
        (RecoveryCaseStatus.DETECTED, CaseTrigger.ELIGIBILITY_PASSED, RecoveryCaseStatus.ELIGIBLE),
        (RecoveryCaseStatus.ELIGIBLE, CaseTrigger.START_ANALYSIS, RecoveryCaseStatus.ANALYZING),
        (RecoveryCaseStatus.ANALYZING, CaseTrigger.SIGNAL_FOUND, RecoveryCaseStatus.ACTION_PROPOSED),
        (RecoveryCaseStatus.ACTION_PROPOSED, CaseTrigger.POLICY_ALLOWED, RecoveryCaseStatus.POLICY_APPROVED),
        (RecoveryCaseStatus.POLICY_APPROVED, CaseTrigger.BEGIN_EXECUTION, RecoveryCaseStatus.EXECUTING),
        (RecoveryCaseStatus.EXECUTING, CaseTrigger.EXECUTION_SUCCEEDED, RecoveryCaseStatus.SUCCEEDED),
    ]
    for from_status, trigger, expected_to in steps:
        result = apply_trigger(snapshot(from_status), trigger, payment_captured=False)
        assert result.applied, f"{from_status} -({trigger})-> expected {expected_to}, was rejected"
        assert result.new_status == expected_to
        assert not result.forced


def test_delayed_retry_path_schedules_then_executes():
    r1 = apply_trigger(
        snapshot(RecoveryCaseStatus.POLICY_APPROVED), CaseTrigger.SCHEDULE, payment_captured=False
    )
    assert r1.applied and r1.new_status == RecoveryCaseStatus.SCHEDULED

    r2 = apply_trigger(
        snapshot(RecoveryCaseStatus.SCHEDULED), CaseTrigger.SCHEDULED_TIME_REACHED, payment_captured=False
    )
    assert r2.applied and r2.new_status == RecoveryCaseStatus.EXECUTING


@pytest.mark.parametrize(
    "starting_status",
    [
        RecoveryCaseStatus.DETECTED,
        RecoveryCaseStatus.ELIGIBLE,
        RecoveryCaseStatus.ANALYZING,
        RecoveryCaseStatus.ACTION_PROPOSED,
        RecoveryCaseStatus.POLICY_APPROVED,
        RecoveryCaseStatus.SCHEDULED,
        RecoveryCaseStatus.EXECUTING,
        RecoveryCaseStatus.FAILED,
    ],
)
def test_payment_already_captured_forces_succeeded_from_any_non_terminal_state(starting_status):
    result = apply_trigger(
        snapshot(starting_status), CaseTrigger.START_ANALYSIS, payment_captured=True
    )
    assert result.applied
    assert result.new_status == RecoveryCaseStatus.SUCCEEDED
    assert result.forced


def test_payment_captured_guard_does_not_refire_once_already_succeeded():
    result = apply_trigger(
        snapshot(RecoveryCaseStatus.SUCCEEDED), CaseTrigger.EXECUTION_SUCCEEDED, payment_captured=True
    )
    # Already SUCCEEDED and terminal — no further transition, not even a "forced" no-op.
    assert not result.applied
    assert result.ignored_reason == "TERMINAL"


def test_failed_retries_to_eligible_under_attempt_budget():
    result = apply_trigger(
        snapshot(RecoveryCaseStatus.FAILED, attempt_count=1, max_attempts=3),
        CaseTrigger.RETRY_CHECK,
        payment_captured=False,
    )
    assert result.applied
    assert result.new_status == RecoveryCaseStatus.ELIGIBLE


def test_failed_expires_once_attempt_budget_exhausted():
    result = apply_trigger(
        snapshot(RecoveryCaseStatus.FAILED, attempt_count=3, max_attempts=3),
        CaseTrigger.RETRY_CHECK,
        payment_captured=False,
    )
    assert result.applied
    assert result.new_status == RecoveryCaseStatus.EXPIRED


def test_hinglish_voice_execution_blocked_without_consent():
    result = apply_trigger(
        snapshot(RecoveryCaseStatus.POLICY_APPROVED),
        CaseTrigger.BEGIN_EXECUTION,
        payment_captured=False,
        action_type=ActionType.HINGLISH_VOICE,
        consent_recorded=False,
    )
    assert not result.applied
    assert result.ignored_reason == "CONSENT_REQUIRED"


def test_hinglish_voice_execution_allowed_with_consent():
    result = apply_trigger(
        snapshot(RecoveryCaseStatus.POLICY_APPROVED),
        CaseTrigger.BEGIN_EXECUTION,
        payment_captured=False,
        action_type=ActionType.HINGLISH_VOICE,
        consent_recorded=True,
    )
    assert result.applied
    assert result.new_status == RecoveryCaseStatus.EXECUTING


def test_illegal_transition_rejected():
    result = apply_trigger(
        snapshot(RecoveryCaseStatus.DETECTED), CaseTrigger.EXECUTION_SUCCEEDED, payment_captured=False
    )
    assert not result.applied
    assert result.ignored_reason == "ILLEGAL_TRANSITION"
