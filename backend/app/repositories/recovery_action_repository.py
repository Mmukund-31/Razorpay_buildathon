"""Recovery action persistence. `idempotency_key` is UNIQUE at the schema level (see the
model) — `get_by_idempotency_key` is what lets the executor check "have I already done this"
before ever calling out to Razorpay or a communication provider.
"""

import uuid

from sqlalchemy import select

from app.domain.models.recovery_action import RecoveryAction
from app.repositories.base_repository import BaseRepository


class RecoveryActionRepository(BaseRepository[RecoveryAction]):
    model = RecoveryAction

    async def get_by_idempotency_key(self, idempotency_key: str) -> RecoveryAction | None:
        result = await self.session.execute(
            select(RecoveryAction).where(RecoveryAction.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def list_for_case(self, recovery_case_id: uuid.UUID) -> list[RecoveryAction]:
        result = await self.session.execute(
            select(RecoveryAction)
            .where(RecoveryAction.recovery_case_id == recovery_case_id)
            .order_by(RecoveryAction.created_at.desc())
        )
        return list(result.scalars())
