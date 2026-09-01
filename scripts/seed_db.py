#!/usr/bin/env python
"""Seeds a handful of demo customers/payments for local manual testing of the dashboard —
a dev convenience, not the synthetic dataset generator (that's
scripts/generate_synthetic_dataset.py, the real ML/benchmark data source).

Deliberately reuses the exact same path a real Razorpay webhook takes — a small, fixed-seed
failure storm posted through `POST /api/webhooks/razorpay` (via
`app/services/simulator_service.py`'s in-process ASGI post, per ADR-004) — rather than
inserting ORM rows directly, so a freshly-seeded database exercises the real pipeline
(state reconstruction, revenue signal, opportunity, case, ML/AI, policy, execution) and the
Command Center has real cases/actions/audit events to show, not synthetic-looking stand-ins.

Usage: python scripts/seed_db.py [--count 20] [--seed 7]
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

DEFAULT_SEED_COUNT = 20
DEFAULT_SEED = 7  # deliberately different from the benchmark's seed=42, so a demo database's
# cases are visibly distinct from the ML/benchmark synthetic dataset, not a coincidental subset


async def _seed(*, count: int, seed: int) -> dict:
    from simulator.generators.failure_storm_generator import generate_failure_storm

    events = generate_failure_storm(count=count, seed=seed)
    results = await simulator_service.post_events(events)
    accepted = sum(1 for r in results if r["status_code"] == 200)

    session_factory = get_sessionmaker()
    processed = 0
    for _ in range(100):
        async with session_factory() as session:
            batch = await poll_once(session)
            processed += batch
            if batch == 0:
                break

    await get_engine().dispose()  # same event loop as the work above — see run_simulator.py
    return {"seeded": count, "accepted": accepted, "events_processed": processed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=DEFAULT_SEED_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    result = asyncio.run(_seed(count=args.count, seed=args.seed))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
