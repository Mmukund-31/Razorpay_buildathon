"""GET /api/dashboard — Command Center metrics. Real aggregate queries
(app/services/dashboard_service.py) — an empty database returns honest zeros, never
placeholder numbers.
"""

from fastapi import APIRouter

from app.api.deps import DbSession
from app.services.dashboard_service import get_dashboard_metrics

router = APIRouter()


@router.get("/dashboard")
async def get_dashboard(db: DbSession) -> dict:
    return await get_dashboard_metrics(db)
