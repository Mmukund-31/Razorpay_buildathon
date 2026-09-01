"""Single Python source of truth for every enum used across the system.

Every DB `CHECK` constraint, every Pydantic schema, and every dispatch table (e.g.
`ActionExecutor`'s handler map) references these — never a duplicated string literal set.
The DB CHECK constraints in `alembic/versions/0001_initial_schema.py` are a defense-in-depth
mirror of these values, not an independent source of truth (see docs/decisions.md ADR-001).
"""

from enum import StrEnum


class PaymentStatus(StrEnum):
    CREATED = "CREATED"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    UNKNOWN = "UNKNOWN"


PAYMENT_TERMINAL_STATUSES = frozenset({PaymentStatus.CAPTURED, PaymentStatus.REFUNDED})


class RecoveryCaseStatus(StrEnum):
    DETECTED = "DETECTED"
    ELIGIBLE = "ELIGIBLE"
    ANALYZING = "ANALYZING"
    ACTION_PROPOSED = "ACTION_PROPOSED"
    POLICY_REJECTED = "POLICY_REJECTED"
    POLICY_APPROVED = "POLICY_APPROVED"
    SCHEDULED = "SCHEDULED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    ABSTAINED = "ABSTAINED"
    EXPIRED = "EXPIRED"


RECOVERY_CASE_TERMINAL_STATUSES = frozenset(
    {
        RecoveryCaseStatus.SUCCEEDED,
        RecoveryCaseStatus.ESCALATED,
        RecoveryCaseStatus.EXPIRED,
        RecoveryCaseStatus.ABSTAINED,
        RecoveryCaseStatus.POLICY_REJECTED,
    }
)

# A "live" case is one that still occupies the single-live-case-per-payment slot
# (see the partial unique index on recovery_cases.payment_id).
RECOVERY_CASE_LIVE_STATUSES = frozenset(
    s for s in RecoveryCaseStatus if s not in {RecoveryCaseStatus.FAILED} | RECOVERY_CASE_TERMINAL_STATUSES
) | {RecoveryCaseStatus.FAILED}
# FAILED is intentionally "live" (it can loop back to ELIGIBLE) — only the five states above
# actually vacate the slot. Kept as an explicit named set rather than inline logic wherever
# the partial index's WHERE clause needs to be mirrored in Python (e.g. eligibility checks).


class ActionType(StrEnum):
    """The 7 allowlisted interventions. Nothing outside this enum can ever reach the executor.

    See docs/razorpay-integration.md for the real-vs-simulated mechanism behind each one.
    """

    SMART_RETRY = "SMART_RETRY"
    DELAYED_RETRY = "DELAYED_RETRY"
    CUSTOMER_NOTIFICATION = "CUSTOMER_NOTIFICATION"
    CUSTOMER_ACTION_REQUEST = "CUSTOMER_ACTION_REQUEST"
    HINGLISH_VOICE = "HINGLISH_VOICE"
    ESCALATION = "ESCALATION"
    NO_ACTION = "NO_ACTION"


class RecoveryActionStatus(StrEnum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class WebhookProcessingStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    IGNORED_STALE = "IGNORED_STALE"


class OpportunityType(StrEnum):
    ONE_TIME_PAYMENT_FAILURE = "ONE_TIME_PAYMENT_FAILURE"
    SUBSCRIPTION_PENDING = "SUBSCRIPTION_PENDING"
    SUBSCRIPTION_HALTED = "SUBSCRIPTION_HALTED"


class OpportunityStatus(StrEnum):
    OPEN = "OPEN"
    CONVERTED_TO_CASE = "CONVERTED_TO_CASE"
    DISMISSED = "DISMISSED"


class AgentDecisionType(StrEnum):
    ML_PREDICTION = "ML_PREDICTION"
    AI_DIAGNOSIS = "AI_DIAGNOSIS"


class PolicyReasonCode(StrEnum):
    ALREADY_RECOVERED = "already_recovered"
    RETRY_LIMIT_REACHED = "retry_limit_reached"
    RECOVERY_WINDOW_EXPIRED = "recovery_window_expired"
    CUSTOMER_OPTED_OUT = "customer_opted_out"
    EXPECTED_VALUE_BELOW_MIN = "expected_value_below_min"
    CONFIDENCE_BELOW_MIN = "confidence_below_min"
    ACTION_NOT_SUPPORTED = "action_not_supported"
    CONSENT_REQUIRED_BUT_MISSING = "consent_required_but_missing"


class BaselineType(StrEnum):
    ALWAYS_RETRY = "ALWAYS_RETRY"
    STATIC_RULES = "STATIC_RULES"
    ML_ONLY = "ML_ONLY"
    RECOVERYOS_FULL = "RECOVERYOS_FULL"


class AuditActor(StrEnum):
    SYSTEM = "SYSTEM"
    AI_AGENT = "AI_AGENT"
    POLICY_ENGINE = "POLICY_ENGINE"
    EXECUTOR = "EXECUTOR"


class AuditEvent(StrEnum):
    """The ledger vocabulary. Every hop of the pipeline logs one of these (see
    docs/architecture.md's data-flow diagram for the expected sequence per case)."""

    PAYMENT_FAILED = "PAYMENT_FAILED"
    PAYMENT_STATE_CHANGED = "PAYMENT_STATE_CHANGED"
    REVENUE_DETECTED = "REVENUE_DETECTED"
    ML_SCORED = "ML_SCORED"
    AI_DIAGNOSED = "AI_DIAGNOSED"
    ACTION_OPTIMIZED = "ACTION_OPTIMIZED"
    POLICY_APPROVED = "POLICY_APPROVED"
    POLICY_REJECTED = "POLICY_REJECTED"
    ACTION_EXECUTED = "ACTION_EXECUTED"
    PAYMENT_RECOVERED = "PAYMENT_RECOVERED"
    EVENT_IGNORED_STALE = "EVENT_IGNORED_STALE"
    EVENT_IGNORED_DUPLICATE = "EVENT_IGNORED_DUPLICATE"
    CASE_ABSTAINED = "CASE_ABSTAINED"
    CASE_EXPIRED = "CASE_EXPIRED"
    CASE_ESCALATED = "CASE_ESCALATED"
