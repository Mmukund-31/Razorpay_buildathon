import pytest

pytestmark = pytest.mark.smoke


@pytest.mark.asyncio
async def test_health_returns_200_with_expected_keys(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) >= {"status", "db", "timestamp", "version"}
    assert body["status"] in ("ok", "degraded")
    assert body["db"] in ("ok", "error")
