"""Shared test fixtures.

Design principle: tests that need nothing but the app object or pure domain logic (smoke,
unit) must be able to run with zero external dependencies. Tests that need a real database
(integration) probe connectivity once per session and self-skip with a clear, actionable
message rather than failing confusingly or — worse — silently faking a pass. See
README.md's "No Docker/Postgres available?" section.
"""

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import register_all_models

register_all_models()

# The repo root (parent of backend/) goes on sys.path so tests — and, later,
# app/agents/ml_predictor.py — can `import ml.features.feature_definitions` without ml/ being
# installed as a separate package. Monorepo convention, not a hack: ml/ and backend/ are
# expected to share this feature contract for real starting Phase 6.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

SKIP_MESSAGE = (
    "PostgreSQL not reachable at DATABASE_URL — run `docker compose up -d postgres` then "
    "`alembic upgrade head` in backend/ to enable this test. "
    "See README.md quickstart."
)


async def _postgres_reachable(database_url: str) -> bool:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 — any connectivity failure means "not reachable"
        return False
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def postgres_available() -> bool:
    return await _postgres_reachable(get_settings().database_url)


@pytest_asyncio.fixture
async def db_session(postgres_available: bool):
    """A real AsyncSession against a migrated database. Skips the test (not a failure) when
    Postgres isn't reachable, so this suite degrades gracefully in environments without
    Docker instead of pretending to have verified something it didn't."""
    if not postgres_available:
        pytest.skip(SKIP_MESSAGE)

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with engine.connect() as conn:
        has_payments_table = await conn.run_sync(
            lambda sync_conn: sync_conn.dialect.has_table(sync_conn, "payments")
        )
    if not has_payments_table:
        await engine.dispose()
        pytest.skip("Database reachable but not migrated — run `alembic upgrade head` in backend/ first.")

    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    """An httpx AsyncClient against the app via ASGI transport. Deliberately does NOT trigger
    FastAPI lifespan (startup/shutdown) — the background worker never starts, so no async task
    needs cleanup, and GET /api/health still works because it opens its own DB session
    on-demand rather than depending on lifespan state.

    Disposes `app.db.session.get_engine()`'s process-cached engine on teardown: pytest-asyncio
    runs each test function in its own event loop, but that engine (and the asyncpg
    connections its pool holds) is `@lru_cache`d at process scope. Without this, a connection
    checked back into the pool under one test's event loop gets handed to a *later* test
    running under a different loop — fatal on Windows' ProactorEventLoop, whose transport is
    tied to the loop that created it. A fresh engine per test keeps every connection bound to
    the loop that's actually still alive.
    """
    from app.db.session import get_engine, get_sessionmaker
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
