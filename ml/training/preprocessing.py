"""Shared feature preprocessing for both the sklearn baseline and the LightGBM model, so both
land in the same artifact shape (a fitted sklearn `Pipeline`) and
`ml/inference/predictor.py` doesn't need to know which model type it loaded.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.features.feature_definitions import FEATURE_NAMES

CATEGORICAL_FEATURES = [
    "payment_method",
    "failure_class",
    "subscription_status",
    "previous_response_to_intervention",
    "candidate_action",
]
NUMERIC_FEATURES = [f for f in FEATURE_NAMES if f not in CATEGORICAL_FEATURES]

assert set(CATEGORICAL_FEATURES) | set(NUMERIC_FEATURES) == set(FEATURE_NAMES), (
    "preprocessing.py's feature lists have drifted from ml/features/feature_definitions.py"
)


def build_preprocessor() -> ColumnTransformer:
    # StandardScaler on numerics isn't needed by LightGBM's tree splits, but it's what fixes
    # LogisticRegression's lbfgs convergence given amount's raw-paise scale (up to ~5M) sits
    # next to 0-1 rate features — harmless for the tree model, necessary for the linear one.
    return ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
            ("num", StandardScaler(), NUMERIC_FEATURES),
        ]
    )
