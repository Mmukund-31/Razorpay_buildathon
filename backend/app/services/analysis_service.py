"""ANALYZING -> ACTION_PROPOSED | ABSTAINED. This is where "AI proposes, optimization
prioritizes" actually happens: the ML Predictor scores every candidate action, the AI
Diagnostician proposes one and explains why, and the Intervention Optimizer combines both
into a ranked list of expected values — never the other way around. Neither the ML predictor
nor the AI diagnostician can write to `recovery_cases` or select an action on their own; this
service is the only caller of `recovery_case_service.transition()` for the SIGNAL_FOUND /
NO_SIGNAL triggers.

Abstention rule (docs/reliability.md): if the ML predictor produces no valid signal for ANY
candidate action, this abstains regardless of what the AI diagnostician said — expected-value
math needs a probability, and the AI's confidence is not a substitute for one (see the
docstring on why below). This is a deliberate, conservative choice: the AI is a proposer, not
an independent authority.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import ai_diagnostician, ml_predictor
from app.agents.prompts import SYSTEM_PROMPT, build_user_prompt
from app.core.logging import get_logger
from app.domain.enums import ActionType, AgentDecisionType, AuditActor, AuditEvent
from app.domain.models.agent_decision import AgentDecision
from app.domain.models.payment import Payment
from app.domain.models.recovery_case import RecoveryCase
from app.domain.recovery_case_state_machine import CaseTrigger
from app.services import ledger_service, recovery_case_service
from app.services.feature_service import build_features
from app.services.optimizer_service import (
    ScoredCandidate,
    intervention_cost_paise,
    rank_candidates,
    risk_cost_paise,
)

logger = get_logger(__name__)

# A bounded nudge toward whatever the AI diagnostician recommended — "AI proposes, optimizer
# decides": the AI's opinion moves the ranking a little, in proportion to its own stated
# confidence, but can never override what the ML-scored expected value says on its own. At
# confidence=1.0 this is at most a 12% boost — enough to break a near-tie, not enough to
# promote a clearly worse action over a clearly better one.
_AI_NUDGE_MAX_FRACTION = 0.12


async def analyze(session: AsyncSession, case: RecoveryCase, correlation_id: uuid.UUID) -> RecoveryCase:
    payment = await session.get(Payment, case.payment_id)
    if payment is None:
        logger.error("analyze() called for a case with no payment row", extra={"case_id": str(case.id)})
        return case

    features = await build_features(session, payment, case)

    ml_predictions: dict[ActionType, ml_predictor.MLPrediction] = {}
    for action in ActionType:
        prediction = await ml_predictor.predict(action, features)
        ml_predictions[action] = prediction
        session.add(
            AgentDecision(
                recovery_case_id=case.id,
                decision_type=AgentDecisionType.ML_PREDICTION.value,
                input_features={**features, "candidate_action": action.value},
                raw_output={
                    "probability_of_recovery": prediction.probability_of_recovery,
                    "model_version": prediction.model_version,
                    "error": prediction.error,
                },
                validated_output=(
                    {"probability_of_recovery": prediction.probability_of_recovery}
                    if prediction.is_valid
                    else None
                ),
                is_valid=prediction.is_valid,
                confidence=prediction.probability_of_recovery,
                latency_ms=prediction.latency_ms,
            )
        )
    await session.flush()

    any_ml_signal = any(p.is_valid for p in ml_predictions.values())
    if any_ml_signal:
        await ledger_service.record(
            session,
            correlation_id=correlation_id,
            entity_type="recovery_case",
            entity_id=case.id,
            event=AuditEvent.ML_SCORED,
            actor=AuditActor.SYSTEM,
            model_version=next((p.model_version for p in ml_predictions.values() if p.model_version), None),
        )

    ai_context = {
        "amount": payment.amount,
        "currency": payment.currency,
        "failure_class": payment.failure_class,
        "error_description": payment.error_description,
        "error_reason": payment.error_reason,
        "attempt_count": case.attempt_count,
        "customer_name": None,
        "customer_history_summary": (
            f"success_rate={features['customer_success_rate']}, "
            f"historical_recovery_rate={features['historical_recovery_rate']}, "
            f"prior_recoveries={features['number_of_prior_recoveries']}"
        ),
        "ml_predictions": {
            a.value: p.probability_of_recovery for a, p in ml_predictions.items() if p.is_valid
        },
    }
    ai_result = await ai_diagnostician.diagnose(
        system_prompt=SYSTEM_PROMPT, user_prompt=build_user_prompt(context=ai_context)
    )
    ai_output = ai_result.output if ai_result.is_valid else None

    session.add(
        AgentDecision(
            recovery_case_id=case.id,
            decision_type=AgentDecisionType.AI_DIAGNOSIS.value,
            input_features={"context_keys": list(ai_context.keys())},
            raw_output=ai_result.raw_output,
            validated_output=ai_output.model_dump(mode="json") if ai_output is not None else None,
            is_valid=ai_result.is_valid,
            confidence=ai_output.confidence if ai_output is not None else None,
            latency_ms=ai_result.latency_ms,
        )
    )
    await session.flush()
    if ai_output is not None:
        await ledger_service.record(
            session,
            correlation_id=correlation_id,
            entity_type="recovery_case",
            entity_id=case.id,
            event=AuditEvent.AI_DIAGNOSED,
            actor=AuditActor.AI_AGENT,
            decision=ai_output.recommended_action.value,
            reason=ai_output.diagnosis,
        )

    if not any_ml_signal:
        # No probability from any candidate action — abstain rather than compute a financial
        # decision on nothing. See module docstring for why the AI diagnosis alone is not
        # treated as a substitute signal here.
        return await recovery_case_service.transition(session, case, CaseTrigger.NO_SIGNAL, correlation_id)

    candidates: list[ScoredCandidate] = []
    for action, prediction in ml_predictions.items():
        if not prediction.is_valid or prediction.probability_of_recovery is None:
            continue
        cost = intervention_cost_paise(action)
        risk = risk_cost_paise(action)
        expected_recovery = prediction.probability_of_recovery * payment.amount
        expected_value = expected_recovery - cost - risk
        if ai_output is not None and ai_output.recommended_action == action:
            expected_value *= 1 + _AI_NUDGE_MAX_FRACTION * ai_output.confidence
        candidates.append(
            ScoredCandidate(
                action_type=action,
                probability_of_recovery=prediction.probability_of_recovery,
                expected_recovery=expected_recovery,
                intervention_cost=cost,
                risk_cost=risk,
                expected_value=expected_value,
            )
        )

    ranked = rank_candidates(candidates)
    best = ranked[0]
    await ledger_service.record(
        session,
        correlation_id=correlation_id,
        entity_type="recovery_case",
        entity_id=case.id,
        event=AuditEvent.ACTION_OPTIMIZED,
        actor=AuditActor.SYSTEM,
        decision=best.action_type.value,
        details={
            "ranked_candidates": [
                {"action": c.action_type.value, "expected_value": round(c.expected_value, 2)}
                for c in ranked
            ]
        },
    )

    return await recovery_case_service.transition(
        session,
        case,
        CaseTrigger.SIGNAL_FOUND,
        correlation_id,
        extra_fields={"selected_action": best.action_type.value},
    )
