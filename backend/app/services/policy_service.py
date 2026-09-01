"""ACTION_PROPOSED -> POLICY_APPROVED | POLICY_REJECTED. Thin orchestration around the
deterministic `PolicyEngine` (app/policies/policy_engine.py) — this module's only job is to
assemble a `PolicyContext` from live database state, persist the resulting
`policy_evaluations` row (which every `recovery_actions` row will later be required to
reference), and drive the case's transition. The policy DECISION itself has zero DB/network
I/O and is fully covered by tests/unit/test_policy_engine.py.

`confidence` for the policy gate is the ML-predicted probability of the SELECTED action
succeeding — not the AI diagnostician's self-reported diagnosis confidence, which is about
how sure the AI is of its *classification*, not of the action's success. Gating financial
approval on the number that actually estimates financial outcome is the more defensible
reading of "confidence_below_min."
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.enums import ActionType, AgentDecisionType
from app.domain.models.agent_decision import AgentDecision
from app.domain.models.customer import Customer
from app.domain.models.payment import Payment
from app.domain.models.policy_evaluation import PolicyEvaluation
from app.domain.models.recovery_case import RecoveryCase
from app.domain.recovery_case_state_machine import CaseTrigger
from app.policies.policy_engine import PolicyEngine
from app.policies.rules import PolicyContext
from app.repositories.policy_evaluation_repository import PolicyEvaluationRepository
from app.services import recovery_case_service
from app.services.optimizer_service import intervention_cost_paise, risk_cost_paise


async def _selected_action_signal(
    session: AsyncSession, case: RecoveryCase, action: ActionType
) -> tuple[float, float]:
    """Re-derives (expected_value, confidence) for the case's selected action from the
    ML_PREDICTION agent_decisions row analysis_service.analyze() persisted — recomputing the
    expected-value formula rather than trusting a stored copy, so it can never drift from
    optimizer_service's actual math."""
    row = (
        await session.execute(
            select(AgentDecision)
            .where(
                AgentDecision.recovery_case_id == case.id,
                AgentDecision.decision_type == AgentDecisionType.ML_PREDICTION.value,
                AgentDecision.is_valid.is_(True),
            )
            .where(AgentDecision.input_features["candidate_action"].as_string() == action.value)
            .order_by(AgentDecision.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None or row.confidence is None:
        return 0.0, 0.0

    probability = float(row.confidence)
    cost = intervention_cost_paise(action)
    risk = risk_cost_paise(action)
    expected_value = probability * case.amount - cost - risk
    return expected_value, probability


async def evaluate_and_transition(
    session: AsyncSession,
    case: RecoveryCase,
    correlation_id: uuid.UUID,
    *,
    consent_recorded: bool = False,
) -> RecoveryCase:
    """`consent_recorded` is caller-supplied (from the API layer / simulator) rather than a
    persisted case-level column, per the spec's flow of "record consent -> evaluate policy ->
    execute" — for HINGLISH_VOICE, consent capture is a real interaction (or, in this build,
    a simulated one) that happens before this call, not something the pipeline can discover
    on its own mid-batch. It is re-recorded onto the `recovery_actions` row itself once the
    executor runs, which is the durable, auditable source of truth (see
    app/executors/handlers/hinglish_voice_handler.py)."""
    if not case.selected_action:
        return case
    action = ActionType(case.selected_action)

    payment = await session.get(Payment, case.payment_id)
    customer = await session.get(Customer, case.customer_id) if case.customer_id else None
    expected_value, confidence = await _selected_action_signal(session, case, action)
    settings = get_settings()

    context = PolicyContext(
        already_recovered=bool(payment and payment.status == "CAPTURED"),
        attempt_count=case.attempt_count,
        max_attempts=case.max_attempts,
        recovery_window_expires_at=case.recovery_window_expires_at,
        now=case.updated_at,
        customer_opted_out=bool(customer and customer.opted_out),
        candidate_action=action,
        opportunity_type="ONE_TIME_PAYMENT_FAILURE",
        expected_value=expected_value,
        min_expected_value=settings.min_expected_value * case.amount,
        confidence=confidence,
        min_confidence=settings.min_confidence,
        consent_recorded=consent_recorded,
    )
    decision = PolicyEngine().evaluate(context)

    await PolicyEvaluationRepository(session).add(
        PolicyEvaluation(
            recovery_case_id=case.id,
            candidate_action=action.value,
            allowed=decision.allowed,
            reason_codes=[c.value for c in decision.reason_codes],
            expected_value=decision.expected_value,
            policy_version=decision.policy_version,
        )
    )
    await session.flush()

    trigger = CaseTrigger.POLICY_ALLOWED if decision.allowed else CaseTrigger.POLICY_DENIED
    return await recovery_case_service.transition(session, case, trigger, correlation_id)
