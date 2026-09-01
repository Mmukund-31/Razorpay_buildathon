"""The Recovery Ledger's write-side helper. Every service that needs to append an audit event
goes through `record()` rather than constructing `AuditLog` rows ad hoc — this is what keeps
the `AuditEvent` vocabulary and required fields consistent across the whole pipeline. It is
also the ONLY place `AuditLogRepository.add()` is called from outside a test, so the
"add-only, no update/delete anywhere" invariant (tests/unit/test_audit_log_immutability.py)
has exactly one call site to audit.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import AuditActor, AuditEvent
from app.domain.models.audit_log import AuditLog
from app.repositories.audit_log_repository import AuditLogRepository


async def record(
    session: AsyncSession,
    *,
    correlation_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    event: AuditEvent,
    actor: AuditActor,
    decision: str | None = None,
    reason: str | None = None,
    model_version: str | None = None,
    policy_version: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    repo = AuditLogRepository(session)
    return await repo.add(
        AuditLog(
            correlation_id=correlation_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event=event.value,
            actor=actor.value,
            decision=decision,
            reason=reason,
            model_version=model_version,
            policy_version=policy_version,
            details=details,
        )
    )
