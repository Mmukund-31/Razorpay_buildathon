"""Async SQLAlchemy engine/session factory.

One engine per process, created lazily so importing this module never opens a connection
(important for `test_app_imports.py`, which must succeed with no database reachable).
"""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency. Overridden in tests via `app.dependency_overrides[get_db]`."""
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        yield session
