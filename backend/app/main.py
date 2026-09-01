"""FastAPI application factory.

Startup: configures logging, verifies DB connectivity (logs a warning, does not crash — a
down DB should surface via GET /api/health as "degraded", not take the whole process down),
and starts the background worker as an asyncio task. Shutdown: signals the worker to stop and
waits for it to exit cleanly.
"""

import asyncio
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

# The repo root (parent of backend/) goes on sys.path before any app.* import runs, so
# `import ml.*` (app/agents/ml_predictor.py) and `import simulator.*` (app/api/simulator.py)
# resolve without ml/ or simulator/ being installed as separate packages — see
# tests/conftest.py for the same convention applied to the test process.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.api.router import api_router  # noqa: E402
from app.core.background_worker import run_forever  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.errors import install_exception_handlers  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.db.base import register_all_models  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402

register_all_models()
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    try:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        logger.info("database connectivity check passed")
    except Exception:  # noqa: BLE001 — startup must not crash on a down DB; /api/health reports it
        logger.warning("database unreachable at startup — /api/health will report degraded")

    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(run_forever(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        await worker_task


def create_app() -> FastAPI:
    app = FastAPI(
        title="RecoveryOS",
        description="Autonomous Revenue Recovery Control Plane",
        version="0.1.0",
        lifespan=lifespan,
    )
    install_exception_handlers(app)

    settings = get_settings()
    origins = settings.cors_origin_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        # allow_credentials is incompatible with a wildcard origin per the CORS spec — this
        # API uses no cookies/session auth (see docs/security.md's frontend-auth note), so
        # there's nothing credentialed to protect either way.
        allow_credentials=origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    return app


app = create_app()
