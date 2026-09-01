"""Policy evaluation persistence — every candidate action the PolicyEngine ever ruled on,
allowed or not. Read-heavy from the decision-trace endpoint; write-only elsewhere."""

import uuid

from sqlalchemy import select

from app.domain.models.policy_evaluation import PolicyEvaluation
from app.repositories.base_repository import BaseRepository


class PolicyEvaluationRepository(BaseRepository[PolicyEvaluation]):
    model = PolicyEvaluation

    async def list_for_case(self, recovery_case_id: uuid.UUID) -> list[PolicyEvaluation]:
        result = await self.session.execute(
            select(PolicyEvaluation)
            .where(PolicyEvaluation.recovery_case_id == recovery_case_id)
            .order_by(PolicyEvaluation.evaluated_at.desc())
        )
        return list(result.scalars())
