"""GET /api/analytics/benchmark — real data only, read from `experiments`/`experiment_results`
(populated exclusively by simulator/benchmark/baseline_runner.py, Phase 18). An empty table
means no benchmark has been run yet — the response says so, it never fabricates numbers.
"""

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession
from app.domain.models.experiment import Experiment
from app.domain.models.experiment_result import ExperimentResult

router = APIRouter()


@router.get("/analytics/benchmark")
async def get_benchmark(db: DbSession) -> dict:
    experiments_result = await db.execute(select(Experiment).order_by(Experiment.created_at.desc()))
    experiments = experiments_result.scalars().all()

    results = []
    for experiment in experiments:
        metric_rows = (
            (
                await db.execute(
                    select(ExperimentResult).where(ExperimentResult.experiment_id == experiment.id)
                )
            )
            .scalars()
            .all()
        )
        results.append(
            {
                "id": str(experiment.id),
                "name": experiment.name,
                "baseline_type": experiment.baseline_type,
                "dataset_ref": experiment.dataset_ref,
                "status": experiment.status,
                "metrics": {m.metric_name: float(m.metric_value) for m in metric_rows if m.segment is None},
            }
        )

    return {"experiments": results}
