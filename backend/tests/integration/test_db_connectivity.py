import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_engine_connects_and_selects_one(db_session):
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1


@pytest.mark.asyncio
async def test_payments_table_exists_after_migration(db_session):
    result = await db_session.execute(
        text("SELECT to_regclass('public.payments') IS NOT NULL AS exists")
    )
    assert result.scalar_one() is True
