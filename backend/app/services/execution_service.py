"""POLICY_APPROVED -> SCHEDULED | EXECUTING -> (stays EXECUTING | ESCALATED | ABSTAINED |
FAILED). The only service allowed to construct an `ActionExecutor` and drive a
`recovery_actions` row through PENDING -> EXECUTING -> SUCCEEDED/FAILED/SKIPPED.

Idempotency: `idempotency_key = f"{case_id}:{action_type}:{attempt_count}"` is looked up
BEFORE any external call — a duplicate invocation (e.g. a re-delivered webhook re-triggering
evaluation) finds the existing row and returns it untouched rather than re-executing.

Policy-bypass prevention: every `RecoveryAction` this service creates carries a
`policy_evaluation_id` pointing at an `allowed=true` row this same call fetched — there is no
path here that constructs one without it.

DELAYED_RETRY is dispatched in two steps: `execute()` creates the `RecoveryAction` row with
`scheduled_for` set and returns immediately (case -> SCHEDULED, nothing external called yet);
`dispatch_due_scheduled_actions()` — polled by the background worker alongside webhook
processing — later finds it once `scheduled_for` has passed and actually runs it. Every other
action dispatches synchronously within `execute()`.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.enums import ActionType, AuditActor, AuditEvent, RecoveryActionStatus, RecoveryCaseStatus
from app.domain.models.customer import Customer
from app.domain.models.payment import Payment
from app.domain.models.policy_evaluation import PolicyEvaluation
from app.domain.models.recovery_action import RecoveryAction
from app.domain.models.recovery_case import RecoveryCase
from app.domain.recovery_case_state_machine import CaseTrigger
from app.executors.action_executor import ActionExecutor
from app.integrations.gateway_factory import get_payment_link_gateway, get_subscription_gateway
from app.repositories.recovery_action_repository import RecoveryActionRepository
from app.services import ledger_service, recovery_case_service
from app.services.communication.provider_interface import CallResult, CommunicationProvider, DeliveryResult
from app.services.communication.simulated_voice_provider import SimulatedVoiceProvider
from app.services.communication.text_provider import TextProvider

logger = get_logger(__name__)

# Actions whose successful dispatch resolves the case immediately — see
# app/domain/recovery_case_state_machine.py's CaseTrigger docstring for why the other 5
# actions deliberately do NOT resolve the case on dispatch alone.
_RESOLVING_TRIGGER_ON_SUCCESS: dict[ActionType, CaseTrigger] = {
    ActionType.ESCALATION: CaseTrigger.ESCALATION_COMPLETE,
    ActionType.NO_ACTION: CaseTrigger.NO_ACTION_COMPLETE,
}

DELAYED_RETRY_DELAY = timedelta(hours=6)


class _RoutingCommunicationProvider(CommunicationProvider):
    """Composes TextProvider + SimulatedVoiceProvider behind one interface so handlers don't
    need to know which underlying provider serves which method."""

    def __init__(self) -> None:
        self._text = TextProvider()
        self._voice = SimulatedVoiceProvider()

    async def send(self, *, channel: str, message: str, recipient: str) -> DeliveryResult:
        return await self._text.send(channel=channel, message=message, recipient=recipient)

    async def place_call(
        self, *, script: str, recipient: str, simulate_response: str = "affirmative"
    ) -> CallResult:
        return await self._voice.place_call(
            script=script, recipient=recipient, simulate_response=simulate_response
        )


def build_executor() -> ActionExecutor:
    return ActionExecutor(
        payment_link_adapter=get_payment_link_gateway(),
        subscription_adapter=get_subscription_gateway(),
        communication_provider=_RoutingCommunicationProvider(),
    )


async def _latest_approved_policy_evaluation(
    session: AsyncSession, case_id: uuid.UUID, action: ActionType
) -> PolicyEvaluation | None:
    result = await session.execute(
        select(PolicyEvaluation)
        .where(
            PolicyEvaluation.recovery_case_id == case_id,
            PolicyEvaluation.candidate_action == action.value,
            PolicyEvaluation.allowed.is_(True),
        )
        .order_by(PolicyEvaluation.evaluated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _dispatch(
    session: AsyncSession,
    case: RecoveryCase,
    recovery_action: RecoveryAction,
    action: ActionType,
    correlation_id: uuid.UUID,
) -> RecoveryCase:
    payment = await session.get(Payment, case.payment_id)
    if payment is None:
        # Should be unreachable — a recovery_case's payment_id is a NOT NULL FK — but a
        # money-moving action must never dispatch against a payment we can't even load.
        raise RuntimeError(f"recovery_case {case.id} references a missing payment {case.payment_id}")
    customer = await session.get(Customer, case.customer_id) if case.customer_id else None

    executor = build_executor()
    try:
        result = await executor.execute(recovery_action, payment, customer)
    except Exception as exc:  # noqa: BLE001 — a failed dispatch must not crash the pipeline
        logger.exception("action execution failed", extra={"action": action.value, "case_id": str(case.id)})
        recovery_action.status = RecoveryActionStatus.FAILED.value
        recovery_action.result = {"error": str(exc)}
        await session.flush()
        await ledger_service.record(
            session,
            correlation_id=correlation_id,
            entity_type="recovery_action",
            entity_id=recovery_action.id,
            event=AuditEvent.ACTION_EXECUTED,
            actor=AuditActor.EXECUTOR,
            decision="FAILED",
            reason=str(exc),
        )
        return await recovery_case_service.transition(
            session,
            case,
            CaseTrigger.EXECUTION_FAILED,
            correlation_id,
            extra_fields={"attempt_count": case.attempt_count + 1},
        )

    recovery_action.status = RecoveryActionStatus.SUCCEEDED.value
    recovery_action.result = result
    recovery_action.executed_at = datetime.now(UTC)
    recovery_action.channel = result.get("channel")
    recovery_action.external_reference = result.get("razorpay_payment_link_id") or result.get(
        "card_change_url"
    )
    await session.flush()

    await ledger_service.record(
        session,
        correlation_id=correlation_id,
        entity_type="recovery_action",
        entity_id=recovery_action.id,
        event=AuditEvent.ACTION_EXECUTED,
        actor=AuditActor.EXECUTOR,
        decision="SUCCEEDED",
        details={"action_type": action.value},
    )

    resolving_trigger = _RESOLVING_TRIGGER_ON_SUCCESS.get(action)
    if resolving_trigger is not None:
        return await recovery_case_service.transition(session, case, resolving_trigger, correlation_id)

    # The 5 real recovery-attempt actions: dispatch succeeded, but the case stays EXECUTING —
    # only a genuine payment.captured webhook (via recovery_case_service's
    # PAYMENT_CAPTURED_EXTERNALLY path) or a future retry/expiry sweep resolves it further.
    return case


async def execute(
    session: AsyncSession,
    case: RecoveryCase,
    correlation_id: uuid.UUID,
    *,
    consent_recorded: bool = False,
) -> RecoveryCase:
    if not case.selected_action:
        return case
    action = ActionType(case.selected_action)

    policy_evaluation = await _latest_approved_policy_evaluation(session, case.id, action)
    if policy_evaluation is None:
        logger.error(
            "execute() called with no approved policy_evaluation — refusing to act",
            extra={"case_id": str(case.id), "action": action.value},
        )
        return case

    idempotency_key = f"{case.id}:{action.value}:{case.attempt_count}"
    action_repo = RecoveryActionRepository(session)
    existing = await action_repo.get_by_idempotency_key(idempotency_key)
    if existing is not None:
        logger.info(
            "recovery_action already exists for this key — idempotent no-op",
            extra={"key": idempotency_key},
        )
        return case

    if action == ActionType.DELAYED_RETRY and case.status == RecoveryCaseStatus.POLICY_APPROVED.value:
        case = await recovery_case_service.transition(session, case, CaseTrigger.SCHEDULE, correlation_id)
        if case.status != RecoveryCaseStatus.SCHEDULED.value:
            return case
        await action_repo.add(
            RecoveryAction(
                recovery_case_id=case.id,
                action_type=action.value,
                status=RecoveryActionStatus.PENDING.value,
                idempotency_key=idempotency_key,
                policy_evaluation_id=policy_evaluation.id,
                consent_recorded=consent_recorded,
                consent_recorded_at=datetime.now(UTC) if consent_recorded else None,
                scheduled_for=datetime.now(UTC) + DELAYED_RETRY_DELAY,
            )
        )
        await session.flush()
        return case

    if case.status == RecoveryCaseStatus.POLICY_APPROVED.value:
        case = await recovery_case_service.transition(
            session,
            case,
            CaseTrigger.BEGIN_EXECUTION,
            correlation_id,
            action_type=action,
            consent_recorded=consent_recorded,
        )
    if case.status != RecoveryCaseStatus.EXECUTING.value:
        return case  # blocked (consent required, lost a race, etc.) — already logged by transition()

    recovery_action = await action_repo.add(
        RecoveryAction(
            recovery_case_id=case.id,
            action_type=action.value,
            status=RecoveryActionStatus.PENDING.value,
            idempotency_key=idempotency_key,
            policy_evaluation_id=policy_evaluation.id,
            consent_recorded=consent_recorded,
            consent_recorded_at=datetime.now(UTC) if consent_recorded else None,
        )
    )
    await session.flush()
    return await _dispatch(session, case, recovery_action, action, correlation_id)


async def dispatch_due_scheduled_actions(session: AsyncSession) -> int:
    """Background-worker-callable sweep: finds PENDING, unscheduled-no-more RecoveryActions
    (DELAYED_RETRY) whose `scheduled_for` has passed, moves their case SCHEDULED -> EXECUTING,
    and dispatches. Returns the count processed."""
    now = datetime.now(UTC)
    due = (
        await session.execute(
            select(RecoveryAction).where(
                RecoveryAction.status == RecoveryActionStatus.PENDING.value,
                RecoveryAction.scheduled_for.is_not(None),
                RecoveryAction.scheduled_for <= now,
            )
        )
    ).scalars()

    count = 0
    for recovery_action in due:
        case = await session.get(RecoveryCase, recovery_action.recovery_case_id)
        if case is None or case.status != RecoveryCaseStatus.SCHEDULED.value:
            continue
        correlation_id = uuid.uuid4()
        action = ActionType(recovery_action.action_type)
        case = await recovery_case_service.transition(
            session, case, CaseTrigger.SCHEDULED_TIME_REACHED, correlation_id
        )
        if case.status != RecoveryCaseStatus.EXECUTING.value:
            continue
        await _dispatch(session, case, recovery_action, action, correlation_id)
        count += 1
    return count
