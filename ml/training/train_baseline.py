#!/usr/bin/env python
"""Trains the sklearn baseline (logistic regression) — the ML_ONLY / calibration-comparison
reference the LightGBM model is judged against. 70/15/15 split already happened at dataset
generation time (ml/data/{train,validation,test}.csv); this script never touches the test
split until the single final evaluation, and never re-tunes based on it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from ml.features.feature_definitions import FEATURE_NAMES
from ml.training.evaluation_report import evaluate
from ml.training.preprocessing import build_preprocessor

DATA_DIR = REPO_ROOT / "ml" / "data"
ARTIFACTS_DIR = REPO_ROOT / "ml" / "training" / "artifacts"
MODEL_NAME = "baseline_logistic_regression"
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
            ("model", LogisticRegression(max_iter=1000, class_weight="balanced")),
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
        "model_type": "sklearn.LogisticRegression",
        "artifact_path": str(artifact_path.relative_to(REPO_ROOT)),
        "features": list(FEATURE_NAMES),
        "validation_metrics": validation_metrics,
        "test_metrics": test_metrics,
    }
    metrics_path = ARTIFACTS_DIR / f"{MODEL_NAME}_{MODEL_VERSION}.metrics.json"
    metrics_path.write_text(json.dumps(result, indent=2))

    print(f"Saved model: {artifact_path}")
    print(f"Saved metrics: {metrics_path}")
    print("\nValidation metrics:")
    print(json.dumps(validation_metrics, indent=2))
    print("\nTest metrics (held-out, evaluated once):")
    print(json.dumps(test_metrics, indent=2))
    return result


if __name__ == "__main__":
    train()
