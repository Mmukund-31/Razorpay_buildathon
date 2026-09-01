"""Agent decision persistence — every ML prediction and AI diagnosis, valid or not (see the
model's docstring for why `is_valid` matters). Read-heavy from the decision-trace endpoint.
"""

import uuid

from sqlalchemy import select

from app.domain.models.agent_decision import AgentDecision
from app.repositories.base_repository import BaseRepository


class AgentDecisionRepository(BaseRepository[AgentDecision]):
    model = AgentDecision

    async def list_for_case(self, recovery_case_id: uuid.UUID) -> list[AgentDecision]:
        result = await self.session.execute(
            select(AgentDecision)
            .where(AgentDecision.recovery_case_id == recovery_case_id)
            .order_by(AgentDecision.created_at.desc())
        )
        return list(result.scalars())
