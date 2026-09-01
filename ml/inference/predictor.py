"""The inference-side counterpart to app/agents/ml_predictor.py — loads a persisted model
artifact (a fitted sklearn `Pipeline`, produced by ml/training/train_lightgbm.py or
train_baseline.py) and scores a feature dict built from ml/features/feature_definitions.py.

Deliberately returns `None` — never a fabricated probability — when no artifact is available,
so the caller can record `is_valid=False` and fall back per docs/reliability.md's "if ML
fails: fallback to safe rule engine or abstain" rule.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ARTIFACTS_DIR = REPO_ROOT / "ml" / "training" / "artifacts"
ACTIVE_MODEL_MANIFEST = ARTIFACTS_DIR / "active_model.json"

from ml.features.feature_definitions import FEATURE_NAMES  # noqa: E402


class ActiveModel:
    """Wraps a loaded artifact + the metadata that identifies it (name/version), so callers
    can record exactly which model produced a prediction without re-deriving it."""

    def __init__(self, pipeline: Any, model_name: str, model_version: str, artifact_path: str):
        self.pipeline = pipeline
        self.model_name = model_name
        self.model_version = model_version
        self.artifact_path = artifact_path

    @property
    def qualified_version(self) -> str:
        return f"{self.model_name}:{self.model_version}"


def load_active_model() -> ActiveModel | None:
    """Reads ml/training/artifacts/active_model.json (written by the training script that
    last "won") and loads the joblib artifact it points at. Returns None — not an
    exception — if no model has been trained yet or the artifact is missing/corrupt; a
    missing model is an operational fact the caller must handle, not a crash.
    """
    if not ACTIVE_MODEL_MANIFEST.exists():
        return None
    try:
        manifest = json.loads(ACTIVE_MODEL_MANIFEST.read_text())
        artifact_path = REPO_ROOT / manifest["artifact_path"]
        import joblib

        pipeline = joblib.load(artifact_path)
        return ActiveModel(
            pipeline=pipeline,
            model_name=manifest["model_name"],
            model_version=manifest["model_version"],
            artifact_path=manifest["artifact_path"],
        )
    except Exception:  # noqa: BLE001 — any load failure means "no model available", not a crash
        return None


def predict_proba(model: ActiveModel, features: dict) -> float:
    """`features` must carry every name in FEATURE_NAMES (including `candidate_action` — the
    model scores one candidate action at a time). Raises KeyError with a clear message on a
    missing feature rather than silently scoring garbage.

    Scores exactly one row — this is what live request-serving uses (one case, one candidate
    action, one HTTP-request-scoped call). For scoring many rows at once (offline evaluation,
    the benchmark), use `predict_proba_batch` instead — a single-row call for each of
    thousands of rows pays per-call sklearn Pipeline overhead thousands of times over for no
    benefit when nothing is waiting on an individual result.
    """
    missing = [f for f in FEATURE_NAMES if f not in features]
    if missing:
        raise KeyError(f"missing required features for prediction: {missing}")

    import pandas as pd

    row = pd.DataFrame([{name: features[name] for name in FEATURE_NAMES}])
    return float(model.pipeline.predict_proba(row)[0, 1])


def predict_proba_batch(model: ActiveModel, feature_rows: list[dict]) -> list[float]:
    """Batched counterpart to `predict_proba` — one Pipeline call for many rows. Used by
    simulator/benchmark/baseline_runner.py, which scores every action for every held-out row.
    """
    if not feature_rows:
        return []
    import pandas as pd

    missing = [f for f in FEATURE_NAMES if f not in feature_rows[0]]
    if missing:
        raise KeyError(f"missing required features for prediction: {missing}")

    frame = pd.DataFrame([{name: row[name] for name in FEATURE_NAMES} for row in feature_rows])
    return [float(p) for p in model.pipeline.predict_proba(frame)[:, 1]]
