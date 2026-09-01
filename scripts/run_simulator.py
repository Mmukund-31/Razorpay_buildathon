#!/usr/bin/env python
"""CLI entrypoint for simulator/ scenarios and failure-storm generation — a thin wrapper over
the SAME code `POST /api/simulator/failure-storm` and `/api/simulator/scenario` call
(`app/services/simulator_service.py`'s in-process ASGI post, per ADR-004: never a parallel
fake path), for scripted demo/CI use without needing the frontend OR a running uvicorn
server — the ASGI transport calls the app directly in-process.

Usage:
    python scripts/run_simulator.py failure-storm --count 100 --seed 42
    python scripts/run_simulator.py scenario duplicate_webhook

After posting events, drains the background worker's pending-event queue
(`app.core.background_worker.poll_once`) so the script's own output reflects events that were
actually processed by the pipeline, not just accepted by the webhook endpoint — requires a
reachable, migrated database (`alembic upgrade head`); if none is reachable, events are still
posted and persisted as PENDING, and the script says so rather than silently under-reporting.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
for _path in (REPO_ROOT, BACKEND_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.core.background_worker import poll_once
from app.db.session import get_engine, get_sessionmaker
from app.services import simulator_service


async def _drain_pending_events(*, max_iterations: int = 100) -> int | None:
    """Returns the total number of events processed, or None if no database was reachable
    (a soft failure, not an error — the events themselves were still accepted/persisted)."""
    try:
        session_factory = get_sessionmaker()
        total = 0
        for _ in range(max_iterations):
            async with session_factory() as session:
                processed = await poll_once(session)
                total += processed
                if processed == 0:
                    break
        return total
    except Exception:  # noqa: BLE001 — no reachable DB is a soft failure for this CLI script
        return None


async def _run_failure_storm(*, count: int, seed: int) -> dict:
    from simulator.generators.failure_storm_generator import generate_failure_storm

    events = generate_failure_storm(count=count, seed=seed)
    results = await simulator_service.post_events(events)
    accepted = sum(1 for r in results if r["status_code"] == 200)
    processed = await _drain_pending_events()
    return {
        "requested": count,
        "accepted": accepted,
        "rejected": count - accepted,
        "events_processed": processed,
    }


async def _run_scenario(name: str) -> dict:
    from simulator.scenarios.scenario_runner import SCENARIO_RUNNERS

    runner = SCENARIO_RUNNERS.get(name)
    if runner is None:
        raise SystemExit(f"Unknown scenario '{name}'. Known: {sorted(SCENARIO_RUNNERS)}")

    batch = runner()
    responses = [await simulator_service.post_event(payload, event_id=event_id) for payload, event_id in batch]
    processed = await _drain_pending_events()
    return {"scenario": name, "events_sent": len(batch), "events_processed": processed, "responses": responses}


async def _run(args: argparse.Namespace) -> dict:
    if args.command == "failure-storm":
        result = await _run_failure_storm(count=args.count, seed=args.seed)
    else:
        result = await _run_scenario(args.name)
    # Disposing the engine must happen in THIS same event loop, not a later separate
    # `asyncio.run()` call — asyncpg connections are bound to the loop that created them, and
    # disposing them from a different (later) loop is exactly the failure this avoids (see
    # tests/conftest.py's `client` fixture for the same fix applied there).
    await get_engine().dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    storm = subparsers.add_parser("failure-storm", help="Generate a batch of synthetic payment failures.")
    storm.add_argument("--count", type=int, default=100)
    storm.add_argument("--seed", type=int, default=42)

    scenario = subparsers.add_parser("scenario", help="Run one named failure-injection scenario.")
    scenario.add_argument("name", help="e.g. duplicate_webhook, out_of_order_webhook, api_timeout")

    args = parser.parse_args()
    result = asyncio.run(_run(args))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
