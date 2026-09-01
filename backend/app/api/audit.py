"""GET /api/audit — a filtered, paginated read of the append-only Recovery Ledger. No write
path is exposed here or anywhere else — see app/repositories/audit_log_repository.py's
docstring for the append-only guarantee this endpoint's absence of a POST/PATCH upholds.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession
from app.domain.models.audit_log import AuditLog

router = APIRouter()


@router.get("/audit")
async def list_audit_entries(
    db: DbSession,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    from_: datetime | None = None,
    to: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    query = select(AuditLog)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
    if from_:
        query = query.where(AuditLog.created_at >= from_)
    if to:
        query = query.where(AuditLog.created_at <= to)

    total = len((await db.execute(query.with_only_columns(AuditLog.id))).all())
    query = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).scalars().all()

    return {
        "items": [
            {
                "id": str(r.id),
                "correlation_id": str(r.correlation_id),
                "entity_type": r.entity_type,
                "entity_id": str(r.entity_id),
                "event": r.event,
                "actor": r.actor,
                "decision": r.decision,
                "reason": r.reason,
                "model_version": r.model_version,
                "policy_version": r.policy_version,
                "details": r.details,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
