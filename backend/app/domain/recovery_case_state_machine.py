"""The recovery case state machine (13 states, see docs/architecture.md for the full
transition table). Pure, in-memory, no I/O — same rationale as payment_state_machine.py.

Two safety invariants are enforced *here*, not just documented:

1. **"A recovered payment can't be retried."** `payment_captured` is checked FIRST, before any
   requested trigger is evaluated, and short-circuits straight to SUCCEEDED regardless of the
   case's current state (as long as it isn't already SUCCEEDED). The caller is required to
   pass a freshly-read `payment_captured` flag every time — never a cached one — which is why
   this function takes it as an explicit parameter rather than trusting `snapshot.status`.
2. **"Retry limits can't be exceeded."** The FAILED state's only way back to ELIGIBLE is the
   `RETRY_CHECK` trigger, which compares `attempt_count` to `max_attempts` and routes to
   EXPIRED once the budget is exhausted — there is no other path out of FAILED.

Durable application (optimistic-locked `WHERE id=:id AND version=:expected` UPDATE) lives in
`app/repositories/recovery_case_repository.py` (Phase 2) and must call `apply_trigger()` first.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from app.domain.enums import RECOVERY_CASE_TERMINAL_STATUSES, ActionType, RecoveryCaseStatus

IgnoredReason = Literal["TERMINAL", "CONSENT_REQUIRED", "ILLEGAL_TRANSITION", "NONE"]


class CaseTrigger(StrEnum):
    ELIGIBILITY_PASSED = "ELIGIBILITY_PASSED"
    CUSTOMER_OPTED_OUT = "CUSTOMER_OPTED_OUT"
    WINDOW_EXPIRED = "WINDOW_EXPIRED"
    START_ANALYSIS = "START_ANALYSIS"
    SIGNAL_FOUND = "SIGNAL_FOUND"
    NO_SIGNAL = "NO_SIGNAL"
    POLICY_ALLOWED = "POLICY_ALLOWED"
    POLICY_DENIED = "POLICY_DENIED"
    SCHEDULE = "SCHEDULE"  # POLICY_APPROVED -> SCHEDULED, used for DELAYED_RETRY
    BEGIN_EXECUTION = "BEGIN_EXECUTION"  # POLICY_APPROVED -> EXECUTING, immediate actions
    SCHEDULED_TIME_REACHED = "SCHEDULED_TIME_REACHED"
    EXECUTION_SUCCEEDED = "EXECUTION_SUCCEEDED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    RETRY_CHECK = "RETRY_CHECK"  # FAILED -> ELIGIBLE | EXPIRED, decided by attempt budget
    # A successfully-dispatched SMART_RETRY/DELAYED_RETRY/CUSTOMER_NOTIFICATION/
    # CUSTOMER_ACTION_REQUEST/HINGLISH_VOICE does NOT resolve the case — sending a payment
    # link or making a call isn't the same moment as the customer actually paying. Those 5
    # actions deliberately have no outbound transition here: app/services/execution_service.py
    # marks the RecoveryAction SUCCEEDED and leaves the case in EXECUTING, to be resolved
    # later by a genuine payment.captured webhook via PAYMENT_CAPTURED_EXTERNALLY below (which
    # relies entirely on the payment_captured guard, not a table entry) or by a future
    # re-evaluation expiring it. ESCALATION and NO_ACTION are the two exceptions: dispatching
    # them IS the whole outcome, so they get their own resolving triggers.
    ESCALATION_COMPLETE = "ESCALATION_COMPLETE"  # EXECUTING -> ESCALATED
    NO_ACTION_COMPLETE = "NO_ACTION_COMPLETE"  # EXECUTING -> ABSTAINED (a deliberate no-op)
    # Never present in _TRANSITIONS on purpose — the payment_captured guard at the top of
    # apply_trigger() always fires first and short-circuits straight to SUCCEEDED. This name
    # exists purely so callers (app/services/recovery_case_service.py) can express "I'm
    # calling transition() because the payment was independently captured" self-documentingly,
    # instead of reusing an unrelated trigger name as a magic no-op carrier.
    PAYMENT_CAPTURED_EXTERNALLY = "PAYMENT_CAPTURED_EXTERNALLY"


_TRANSITIONS: dict[tuple[RecoveryCaseStatus, CaseTrigger], RecoveryCaseStatus] = {
    (RecoveryCaseStatus.DETECTED, CaseTrigger.ELIGIBILITY_PASSED): RecoveryCaseStatus.ELIGIBLE,
    (RecoveryCaseStatus.DETECTED, CaseTrigger.CUSTOMER_OPTED_OUT): RecoveryCaseStatus.ABSTAINED,
    (RecoveryCaseStatus.DETECTED, CaseTrigger.WINDOW_EXPIRED): RecoveryCaseStatus.EXPIRED,
    (RecoveryCaseStatus.ELIGIBLE, CaseTrigger.START_ANALYSIS): RecoveryCaseStatus.ANALYZING,
    (RecoveryCaseStatus.ANALYZING, CaseTrigger.SIGNAL_FOUND): RecoveryCaseStatus.ACTION_PROPOSED,
    (RecoveryCaseStatus.ANALYZING, CaseTrigger.NO_SIGNAL): RecoveryCaseStatus.ABSTAINED,
    (RecoveryCaseStatus.ACTION_PROPOSED, CaseTrigger.POLICY_ALLOWED): RecoveryCaseStatus.POLICY_APPROVED,
    (RecoveryCaseStatus.ACTION_PROPOSED, CaseTrigger.POLICY_DENIED): RecoveryCaseStatus.POLICY_REJECTED,
    (RecoveryCaseStatus.POLICY_APPROVED, CaseTrigger.SCHEDULE): RecoveryCaseStatus.SCHEDULED,
    (RecoveryCaseStatus.POLICY_APPROVED, CaseTrigger.BEGIN_EXECUTION): RecoveryCaseStatus.EXECUTING,
    (RecoveryCaseStatus.SCHEDULED, CaseTrigger.SCHEDULED_TIME_REACHED): RecoveryCaseStatus.EXECUTING,
    (RecoveryCaseStatus.EXECUTING, CaseTrigger.EXECUTION_SUCCEEDED): RecoveryCaseStatus.SUCCEEDED,
    (RecoveryCaseStatus.EXECUTING, CaseTrigger.EXECUTION_FAILED): RecoveryCaseStatus.FAILED,
    (RecoveryCaseStatus.EXECUTING, CaseTrigger.ESCALATION_COMPLETE): RecoveryCaseStatus.ESCALATED,
    (RecoveryCaseStatus.EXECUTING, CaseTrigger.NO_ACTION_COMPLETE): RecoveryCaseStatus.ABSTAINED,
}


@dataclass(frozen=True, slots=True)
class RecoveryCaseSnapshot:
    status: RecoveryCaseStatus
    attempt_count: int
    max_attempts: int
    version: int


@dataclass(frozen=True, slots=True)
class CaseTransitionResult:
    applied: bool
    new_status: RecoveryCaseStatus | None
    forced: bool  # True when the payment-already-captured guard overrode the requested trigger
    ignored_reason: IgnoredReason


def apply_trigger(
    snapshot: RecoveryCaseSnapshot,
    trigger: CaseTrigger,
    *,
    payment_captured: bool,
    action_type: ActionType | None = None,
    consent_recorded: bool = True,
) -> CaseTransitionResult:
    """Decide the new case status for `trigger`, or explain why it was ignored.

    `payment_captured` must be a value freshly read from the payments table by the caller —
    this function has no way to detect a stale flag itself, so trusting a cached value here
    would defeat the entire "recovered payment can't be retried" guarantee.
    """
    if payment_captured and snapshot.status != RecoveryCaseStatus.SUCCEEDED:
        return CaseTransitionResult(True, RecoveryCaseStatus.SUCCEEDED, True, "NONE")

    if snapshot.status in RECOVERY_CASE_TERMINAL_STATUSES:
        return CaseTransitionResult(False, None, False, "TERMINAL")

    if snapshot.status == RecoveryCaseStatus.FAILED and trigger == CaseTrigger.RETRY_CHECK:
        if snapshot.attempt_count < snapshot.max_attempts:
            return CaseTransitionResult(True, RecoveryCaseStatus.ELIGIBLE, False, "NONE")
        return CaseTransitionResult(True, RecoveryCaseStatus.EXPIRED, False, "NONE")

    if (
        trigger == CaseTrigger.BEGIN_EXECUTION
        and action_type == ActionType.HINGLISH_VOICE
        and not consent_recorded
    ):
        return CaseTransitionResult(False, None, False, "CONSENT_REQUIRED")

    to_status = _TRANSITIONS.get((snapshot.status, trigger))
    if to_status is None:
        return CaseTransitionResult(False, None, False, "ILLEGAL_TRANSITION")

    return CaseTransitionResult(True, to_status, False, "NONE")


def can_transition(
    snapshot: RecoveryCaseSnapshot,
    trigger: CaseTrigger,
    *,
    payment_captured: bool,
    action_type: ActionType | None = None,
    consent_recorded: bool = True,
) -> bool:
    return apply_trigger(
        snapshot,
        trigger,
        payment_captured=payment_captured,
        action_type=action_type,
        consent_recorded=consent_recorded,
    ).applied
