#!/usr/bin/env python
"""Trains the LightGBM model backing the real ML Predictor (app/agents/ml_predictor.py). Same
dataset/split/leakage discipline as train_baseline.py — see that module's docstring.

Model selection rationale (docs/decisions.md "Why tabular ML"): gradient-boosted trees are
the standard strong baseline for small, structured, tabular problems like this one, and their
probability outputs are more directly calibratable than a deep model's — which matters
because this probability feeds straight into a financial expected-value calculation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.pipeline import Pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from ml.features.feature_definitions import FEATURE_NAMES
from ml.training.evaluation_report import evaluate
from ml.training.preprocessing import build_preprocessor

DATA_DIR = REPO_ROOT / "ml" / "data"
ARTIFACTS_DIR = REPO_ROOT / "ml" / "training" / "artifacts"
MODEL_NAME = "lightgbm_recovery_predictor"
MODEL_VERSION = "v1"


def _load_xy(path: Path) -> tuple[pd.DataFrame, pd.Series]:
    df = pd.read_csv(path)
    return df[list(FEATURE_NAMES)], df["actual_recovered"].astype(int)


def train() -> dict:
    x_train, y_train = _load_xy(DATA_DIR / "train.csv")
    x_val, y_val = _load_xy(DATA_DIR / "validation.csv")
    x_test, y_test = _load_xy(DATA_DIR / "test.csv")

    pipeline = Pipeline(
        [
            ("preprocess", build_preprocessor()),
            (
                "model",
                LGBMClassifier(
                    n_estimators=300,
                    learning_rate=0.05,
                    num_leaves=31,
                    max_depth=-1,
                    class_weight="balanced",
                    random_state=42,
                    verbosity=-1,
                ),
            ),
        ]
    )
    pipeline.fit(x_train, y_train)

    validation_metrics = evaluate(pipeline, x_val, y_val)
    test_metrics = evaluate(pipeline, x_test, y_test)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = ARTIFACTS_DIR / f"{MODEL_NAME}_{MODEL_VERSION}.joblib"
    joblib.dump(pipeline, artifact_path)

    result = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "model_type": "lightgbm.LGBMClassifier",
        "artifact_path": str(artifact_path.relative_to(REPO_ROOT)),
        "features": list(FEATURE_NAMES),
        "validation_metrics": validation_metrics,
        "test_metrics": test_metrics,
    }
    metrics_path = ARTIFACTS_DIR / f"{MODEL_NAME}_{MODEL_VERSION}.metrics.json"
    metrics_path.write_text(json.dumps(result, indent=2))

    active_path = ARTIFACTS_DIR / "active_model.json"
    active_path.write_text(
        json.dumps(
            {
                "model_name": MODEL_NAME,
                "model_version": MODEL_VERSION,
                "artifact_path": result["artifact_path"],
            },
            indent=2,
        )
    )

    print(f"Saved model: {artifact_path}")
    print(f"Saved metrics: {metrics_path}")
    print(f"Marked active: {active_path}")
    print("\nValidation metrics:")
    print(json.dumps(validation_metrics, indent=2))
    print("\nTest metrics (held-out, evaluated once):")
    print(json.dumps(test_metrics, indent=2))
    return result


if __name__ == "__main__":
    train()
