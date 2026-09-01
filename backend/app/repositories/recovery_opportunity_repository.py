"""Recovery opportunity persistence. Duplicate-opportunity prevention is the
`UNIQUE(payment_id, opportunity_type)` constraint (see the model) — this repository catches
the resulting IntegrityError the same way webhook ingestion catches a duplicate event_id.
"""

import uuid

from sqlalchemy import select

from app.domain.models.recovery_opportunity import RecoveryOpportunity
from app.repositories.base_repository import BaseRepository


class RecoveryOpportunityRepository(BaseRepository[RecoveryOpportunity]):
    model = RecoveryOpportunity

    async def get_by_payment_and_type(
        self, payment_id: uuid.UUID, opportunity_type: str
    ) -> RecoveryOpportunity | None:
        result = await self.session.execute(
            select(RecoveryOpportunity).where(
                RecoveryOpportunity.payment_id == payment_id,
                RecoveryOpportunity.opportunity_type == opportunity_type,
            )
        )
        return result.scalar_one_or_none()
