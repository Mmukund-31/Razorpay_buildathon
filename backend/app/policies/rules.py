"""The 8 deterministic policy rules, each a pure function `(context) -> PolicyReasonCode |
None` — returns the reason code if the rule REJECTS, `None` if it passes.
`PolicyEngine.evaluate()` runs all of them and rejects if any fired, allows only if none did.
"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import ActionType, PolicyReasonCode

# Actions that require explicit recorded consent before execution — mirrors the
# consent guard already enforced in app/domain/recovery_case_state_machine.py for
# HINGLISH_VOICE; kept as a set here so a future action can opt in without touching the
# state machine.
CONSENT_REQUIRED_ACTIONS = frozenset({ActionType.HINGLISH_VOICE})

# Which actions are even meaningful for a given opportunity type — a subscription-only lever
# (nothing in this build yet) attempted against a one-time payment, or vice versa, should be
# rejected rather than silently attempted. One-time payments support every action except none
# are subscription-specific in Phase 1-21's scope, so this is currently permissive but
# structured so a future subscription-only action slots in without a design change.
_UNSUPPORTED_ACTIONS_BY_OPPORTUNITY_TYPE: dict[str, frozenset[ActionType]] = {
    "ONE_TIME_PAYMENT_FAILURE": frozenset(),
    "SUBSCRIPTION_PENDING": frozenset(),
    "SUBSCRIPTION_HALTED": frozenset(),
}


@dataclass(frozen=True, slots=True)
class PolicyContext:
    already_recovered: bool
    attempt_count: int
    max_attempts: int
    recovery_window_expires_at: datetime | None
    now: datetime
    customer_opted_out: bool
    candidate_action: ActionType
    opportunity_type: str
    expected_value: float
    min_expected_value: float
    confidence: float | None
    min_confidence: float
    consent_recorded: bool


def check_already_recovered(context: PolicyContext) -> PolicyReasonCode | None:
    return PolicyReasonCode.ALREADY_RECOVERED if context.already_recovered else None


def check_retry_limit_reached(context: PolicyContext) -> PolicyReasonCode | None:
    if context.attempt_count >= context.max_attempts:
        return PolicyReasonCode.RETRY_LIMIT_REACHED
    return None


def check_recovery_window_expired(context: PolicyContext) -> PolicyReasonCode | None:
    if context.recovery_window_expires_at is not None and context.now >= context.recovery_window_expires_at:
        return PolicyReasonCode.RECOVERY_WINDOW_EXPIRED
    return None


def check_customer_opted_out(context: PolicyContext) -> PolicyReasonCode | None:
    return PolicyReasonCode.CUSTOMER_OPTED_OUT if context.customer_opted_out else None


def check_expected_value_below_min(context: PolicyContext) -> PolicyReasonCode | None:
    if context.expected_value <= context.min_expected_value:
        return PolicyReasonCode.EXPECTED_VALUE_BELOW_MIN
    return None


def check_confidence_below_min(context: PolicyContext) -> PolicyReasonCode | None:
    if context.confidence is not None and context.confidence < context.min_confidence:
        return PolicyReasonCode.CONFIDENCE_BELOW_MIN
    return None


def check_action_not_supported(context: PolicyContext) -> PolicyReasonCode | None:
    unsupported = _UNSUPPORTED_ACTIONS_BY_OPPORTUNITY_TYPE.get(context.opportunity_type, frozenset())
    if context.candidate_action in unsupported:
        return PolicyReasonCode.ACTION_NOT_SUPPORTED
    return None


def check_consent_required_but_missing(context: PolicyContext) -> PolicyReasonCode | None:
    if context.candidate_action in CONSENT_REQUIRED_ACTIONS and not context.consent_recorded:
        return PolicyReasonCode.CONSENT_REQUIRED_BUT_MISSING
    return None


ALL_RULES = (
    check_already_recovered,
    check_retry_limit_reached,
    check_recovery_window_expired,
    check_customer_opted_out,
    check_expected_value_below_min,
    check_confidence_below_min,
    check_action_not_supported,
    check_consent_required_but_missing,
)
