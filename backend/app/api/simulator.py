"""Simulator endpoints — real. Both generators drive events through the SAME ingestion/
pipeline code real Razorpay webhooks use, via `app/services/simulator_service.py`'s
signed-ASGI-post mechanism — never a separate fake path (ADR-004).
"""

from fastapi import APIRouter, Body, status

from app.core.errors import AppError
from app.services import simulator_service

router = APIRouter()


@router.post("/simulator/failure-storm")
async def failure_storm(
    scenario: str = Body(default="default"),
    count: int = Body(default=100),
    seed: int = Body(default=42),
) -> dict:
    from simulator.generators.failure_storm_generator import generate_failure_storm

    if count > 2000:
        raise AppError(
            code="FAILURE_STORM_TOO_LARGE",
            message="count must be <= 2000 for a synchronous demo run.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    events = generate_failure_storm(count=count, seed=seed)
    results = await simulator_service.post_events(events)
    accepted = sum(1 for r in results if r["status_code"] == 200)
    return {"requested": count, "accepted": accepted, "rejected": count - accepted}


@router.post("/simulator/scenario")
async def run_scenario(
    scenario_name: str = Body(...),
    params: dict = Body(default_factory=dict),
) -> dict:
    from simulator.scenarios.scenario_runner import SCENARIO_RUNNERS

    runner = SCENARIO_RUNNERS.get(scenario_name)
    if runner is None:
        raise AppError(
            code="UNKNOWN_SCENARIO",
            message=f"Unknown scenario '{scenario_name}'. Known: {sorted(SCENARIO_RUNNERS)}",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    batch = runner()
    responses = []
    for payload, forced_event_id in batch:
        result = await simulator_service.post_event(payload, event_id=forced_event_id)
        responses.append(result)

    return {"scenario": scenario_name, "events_sent": len(batch), "responses": responses}
