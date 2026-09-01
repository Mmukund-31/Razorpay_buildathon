"""Interface between the backend and the trained ML model in ml/inference/predictor.py.

Estimates P(successful recovery | context, candidate_action). Never fabricates a probability:
if no model artifact is available, or the feature vector can't be built, this returns
`MLPrediction(is_valid=False, ...)` — the optimizer treats that as no signal (see
docs/reliability.md's "if ML fails: fallback to safe rule engine or abstain" rule), never a
default guess.

The model is loaded once per process (module-level cache) — reloading a joblib artifact per
prediction would be needlessly slow for something that only changes when a new model is
trained and `ml/training/artifacts/active_model.json` is rewritten.
"""

import sys
import time
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ml.inference.predictor import ActiveModel, load_active_model, predict_proba  # noqa: E402

from app.core.logging import get_logger  # noqa: E402
from app.domain.enums import ActionType  # noqa: E402

logger = get_logger(__name__)

_cached_model: ActiveModel | None = None
_cache_attempted = False


def _get_model() -> ActiveModel | None:
    global _cached_model, _cache_attempted
    if not _cache_attempted:
        _cached_model = load_active_model()
        _cache_attempted = True
        if _cached_model is None:
            logger.warning("no active ML model artifact found — ML predictions will be invalid")
    return _cached_model


def reset_cache() -> None:
    """Test/ops hook — forces the next predict() to reload the artifact (e.g. after
    retraining) rather than serving a stale in-process model forever."""
    global _cached_model, _cache_attempted
    _cached_model, _cache_attempted = None, False


@dataclass(frozen=True, slots=True)
class MLPrediction:
    is_valid: bool
    probability_of_recovery: float | None
    model_version: str | None
    latency_ms: int
    error: str | None = None


async def predict(action: ActionType, features: dict) -> MLPrediction:
    start = time.perf_counter()
    model = _get_model()
    if model is None:
        return MLPrediction(
            is_valid=False,
            probability_of_recovery=None,
            model_version=None,
            latency_ms=int((time.perf_counter() - start) * 1000),
            error="no_active_model",
        )

    try:
        row = dict(features)
        row["candidate_action"] = action.value
        probability = predict_proba(model, row)
    except Exception as exc:  # noqa: BLE001 — any inference failure means "no signal," not a crash
        logger.exception("ML prediction failed", extra={"action": action.value})
        return MLPrediction(
            is_valid=False,
            probability_of_recovery=None,
            model_version=model.qualified_version,
            latency_ms=int((time.perf_counter() - start) * 1000),
            error=str(exc),
        )

    return MLPrediction(
        is_valid=True,
        probability_of_recovery=probability,
        model_version=model.qualified_version,
        latency_ms=int((time.perf_counter() - start) * 1000),
    )
