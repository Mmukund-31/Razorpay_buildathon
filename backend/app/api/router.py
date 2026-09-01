"""Aggregates every route module under a single /api prefix."""

from fastapi import APIRouter

from app.api import analytics, audit, dashboard, health, recovery_cases, simulator, webhooks

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(dashboard.router, tags=["dashboard"])
api_router.include_router(recovery_cases.router, tags=["recovery-cases"])
api_router.include_router(webhooks.router, tags=["webhooks"])
api_router.include_router(simulator.router, tags=["simulator"])
api_router.include_router(analytics.router, tags=["analytics"])
api_router.include_router(audit.router, tags=["audit"])
