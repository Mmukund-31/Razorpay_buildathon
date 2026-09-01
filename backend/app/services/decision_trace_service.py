"""Assembles the full explainability payload for GET
/api/recovery-cases/{id}/decision-trace: payment context, every ML prediction, the AI
diagnosis, every candidate's recomputed expected value, the selected action, the policy
decision, and the execution outcome. Read-only — reconstructs everything from
agent_decisions/policy_evaluations/recovery_actions rather than duplicating state anywhere.
"""


from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import ActionType, AgentDecisionType
from app.domain.models.payment import Payment
from app.domain.models.recovery_case import RecoveryCase
from app.domain.schemas.ai_diagnosis import AIDiagnosisOutput
from app.domain.schemas.decision_trace import (
    CandidateAction,
    DecisionTraceResponse,
    ExecutionRecord,
    PaymentContext,
)
from app.domain.schemas.policy_decision import PolicyDecision
from app.repositories.agent_decision_repository import AgentDecisionRepository
from app.repositories.policy_evaluation_repository import PolicyEvaluationRepository
from app.repositories.recovery_action_repository import RecoveryActionRepository
from app.services.optimizer_service import intervention_cost_paise, risk_cost_paise


def _derive_outcome(case: RecoveryCase) -> str | None:
    outcomes = {
        "SUCCEEDED": "Payment recovered.",
        "FAILED": "Execution failed; may retry within the attempt budget.",
        "ABSTAINED": "System abstained — no reliable signal or a deliberate no-action decision.",
        "EXPIRED": "Recovery window or retry budget exhausted without resolution.",
        "ESCALATED": "Escalated for manual/compliance follow-up.",
        "POLICY_REJECTED": "Blocked by policy before any action was taken.",
    }
    return outcomes.get(case.status)


async def build(session: AsyncSession, case: RecoveryCase, payment: Payment) -> DecisionTraceResponse:
    agent_decisions = await AgentDecisionRepository(session).list_for_case(case.id)
    policy_evaluations = await PolicyEvaluationRepository(session).list_for_case(case.id)
    actions = await RecoveryActionRepository(session).list_for_case(case.id)

    ml_rows = [d for d in agent_decisions if d.decision_type == AgentDecisionType.ML_PREDICTION.value]
    ai_rows = [d for d in agent_decisions if d.decision_type == AgentDecisionType.AI_DIAGNOSIS.value]

    candidates: list[CandidateAction] = []
    ml_score: float | None = None
    for row in ml_rows:
        if not row.is_valid or row.confidence is None:
            continue
        action_value = (row.input_features or {}).get("candidate_action")
        if not isinstance(action_value, str):
            continue
        try:
            action_type = ActionType(action_value)
        except ValueError:
            continue
        cost = intervention_cost_paise(action_type)
        risk = risk_cost_paise(action_type)
        expected_recovery = row.confidence * payment.amount
        candidates.append(
            CandidateAction(
                action_type=action_type,
                recovery_probability=row.confidence,
                expected_recovery=expected_recovery,
                intervention_cost=cost,
                risk_cost=risk,
                expected_value=expected_recovery - cost - risk,
            )
        )
        if case.selected_action == action_value:
            ml_score = row.confidence
    candidates.sort(key=lambda c: c.expected_value, reverse=True)

    ai_diagnosis: AIDiagnosisOutput | None = None
    if ai_rows and ai_rows[0].is_valid and ai_rows[0].validated_output:
        ai_diagnosis = AIDiagnosisOutput.model_validate(ai_rows[0].validated_output)

    latest_policy = None
    if case.selected_action:
        matching = [p for p in policy_evaluations if p.candidate_action == case.selected_action]
        latest_policy = matching[0] if matching else None

    latest_action = actions[0] if actions else None

    return DecisionTraceResponse(
        recovery_case_id=case.id,
        status=case.status,  # type: ignore[arg-type]
        payment=PaymentContext(
            payment_id=payment.id,
            razorpay_payment_id=payment.razorpay_payment_id,
            amount=payment.amount,
            currency=payment.currency,
            status=payment.status,
            failure_class=payment.failure_class,
            error_reason=payment.error_reason,
        ),
        ml_score=ml_score,
        ai_diagnosis=ai_diagnosis,
        candidates=candidates,
        selected_action=ActionType(case.selected_action) if case.selected_action else None,
        policy_decision=(
            None
            if latest_policy is None
            else PolicyDecision(
                allowed=latest_policy.allowed,
                reason_codes=latest_policy.reason_codes,
                policy_version=latest_policy.policy_version,
                expected_value=(
                    float(latest_policy.expected_value) if latest_policy.expected_value is not None else None
                ),
            )
        ),
        execution=(
            None
            if latest_action is None
            else ExecutionRecord(
                action_type=ActionType(latest_action.action_type),
                status=latest_action.status,
                channel=latest_action.channel,
                external_reference=latest_action.external_reference,
                executed_at=latest_action.executed_at,
                result=latest_action.result,
                consent_recorded=latest_action.consent_recorded,
            )
        ),
        outcome=_derive_outcome(case),
        actual_recovered_amount=case.actual_recovered_amount,
    )
