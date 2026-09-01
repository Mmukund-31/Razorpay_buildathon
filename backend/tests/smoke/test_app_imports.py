import pytest
from fastapi import FastAPI

pytestmark = pytest.mark.smoke

EXPECTED_ROUTE_PREFIXES = {
    "/api/health",
    "/api/dashboard",
    "/api/recovery-cases",
    "/api/webhooks/razorpay",
    "/api/simulator/failure-storm",
    "/api/analytics/benchmark",
    "/api/audit",
}


def test_app_imports_and_is_fastapi_instance():
    from app.main import app

    assert isinstance(app, FastAPI)


def test_all_expected_routes_registered():
    # Read the OpenAPI schema rather than walking app.routes directly — FastAPI's internal
    # route-wrapper types have changed shape across versions, but the generated schema is the
    # stable, public contract this test actually cares about.
    from app.main import app

    registered_paths = set(app.openapi()["paths"].keys())
    for expected in EXPECTED_ROUTE_PREFIXES:
        assert expected in registered_paths, f"missing route: {expected}"
