"""Recovery case persistence, including the optimistic-locked UPDATE
(`WHERE id=:id AND version=:expected`) that makes concurrent-transition safety durable — see
app/domain/recovery_case_state_machine.py's docstring.
"""

import uuid
from typing import cast

from sqlalchemy import CursorResult, select, update

from app.domain.enums import RECOVERY_CASE_LIVE_STATUSES
from app.domain.models.recovery_case import RecoveryCase
from app.repositories.base_repository import BaseRepository


class RecoveryCaseRepository(BaseRepository[RecoveryCase]):
    model = RecoveryCase

    async def apply_state_transition(
        self,
        *,
        case_id: uuid.UUID,
        expected_version: int,
        new_status: str,
        extra_fields: dict | None = None,
    ) -> bool:
        """Returns True if the optimistic-locked UPDATE succeeded, False if `version` had
        already moved (another worker won the race) — caller should re-read and retry or
        abandon per its own policy, never blindly overwrite."""
        stmt = (
            update(RecoveryCase)
            .where(RecoveryCase.id == case_id, RecoveryCase.version == expected_version)
            .values(status=new_status, version=expected_version + 1, **(extra_fields or {}))
        )
        result = cast(CursorResult, await self.session.execute(stmt))
        return result.rowcount > 0

    async def set_actual_recovered_amount(
        self, *, case_id: uuid.UUID, amount: int, resolved_payment_id: uuid.UUID
    ) -> bool:
        """Conditional UPDATE guarded by `actual_recovered_amount IS NULL` — the durable half
        of "write once, never additive/duplicated" for the amount actually recovered.
        Deliberately separate from `apply_state_transition()` (version-guarded, status-only):
        the amount write and the status transition are two independent idempotency concerns,
        and this one must survive even if the status transition above it loses its optimistic
        lock race on a given attempt (a retry hits the same `IS NULL` guard and is a no-op).
        Returns False if another worker already wrote it — a safe no-op, not an error."""
        stmt = (
            update(RecoveryCase)
            .where(RecoveryCase.id == case_id, RecoveryCase.actual_recovered_amount.is_(None))
            .values(actual_recovered_amount=amount, resolved_payment_id=resolved_payment_id)
        )
        result = cast(CursorResult, await self.session.execute(stmt))
        return result.rowcount > 0

    async def get_live_case_for_payment(self, payment_id: uuid.UUID) -> RecoveryCase | None:
        """At most one row can ever match — enforced by the partial unique index on
        `recovery_cases(payment_id) WHERE status NOT IN (...)`, not just this query's LIMIT."""
        result = await self.session.execute(
            select(RecoveryCase)
            .where(
                RecoveryCase.payment_id == payment_id,
                RecoveryCase.status.in_([s.value for s in RECOVERY_CASE_LIVE_STATUSES]),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_filtered(
        self, *, status: str | None = None, page: int = 1, page_size: int = 25
    ) -> tuple[list[RecoveryCase], int]:
        query = select(RecoveryCase)
        if status:
            query = query.where(RecoveryCase.status == status)
        count_result = await self.session.execute(query.with_only_columns(RecoveryCase.id))
        total = len(count_result.all())
        query = (
            query.order_by(RecoveryCase.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(query)
        return list(result.scalars()), total
