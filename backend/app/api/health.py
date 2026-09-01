"""GET /api/health — REAL. Runs `SELECT 1` against the database and reports degraded, not
crashed, if it fails (see docs/architecture.md's failure-handling table)."""

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

APP_VERSION = "0.1.0"


@router.get("/health")
async def health(db: DbSession) -> dict:
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 — health check must never raise, only report degraded
        logger.exception("health check: database unreachable")
        db_status = "error"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "db": db_status,
        "timestamp": datetime.now(UTC).isoformat(),
        "version": APP_VERSION,
    }
