"""Shared held-out evaluation for a fitted (Pipeline, X, y) triple — used identically by
train_baseline.py and train_lightgbm.py so the two models are compared on exactly the same
metrics computed exactly the same way.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)


def evaluate(model, x, y) -> dict:
    probabilities = model.predict_proba(x)[:, 1]
    predictions = (probabilities >= 0.5).astype(int)

    return {
        "n": len(y),
        "positive_rate": round(float(np.mean(y)), 4),
        "roc_auc": round(float(roc_auc_score(y, probabilities)), 4),
        "average_precision": round(float(average_precision_score(y, probabilities)), 4),
        "precision_at_0.5": round(float(precision_score(y, predictions, zero_division=0)), 4),
        "recall_at_0.5": round(float(recall_score(y, predictions, zero_division=0)), 4),
        "f1_at_0.5": round(float(f1_score(y, predictions, zero_division=0)), 4),
        "log_loss": round(float(log_loss(y, probabilities)), 4),
        "brier_score": round(float(brier_score_loss(y, probabilities)), 4),
        "calibration_error": round(_expected_calibration_error(y, probabilities), 4),
    }


def _expected_calibration_error(y, probabilities, n_bins: int = 10) -> float:
    """Mean absolute gap between predicted probability and observed frequency, averaged
    across `n_bins` equal-width probability bins, weighted by bin size — the standard ECE
    used to judge whether a probability that feeds directly into a financial expected-value
    calculation can actually be trusted."""
    y = np.asarray(y)
    probabilities = np.asarray(probabilities)
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    total = len(y)
    if total == 0:
        return 0.0

    error = 0.0
    for lo, hi in pairwise(bin_edges):
        upper_bound = probabilities <= hi if hi >= 1.0 else probabilities < hi
        mask = (probabilities >= lo) & upper_bound
        if not mask.any():
            continue
        bin_confidence = probabilities[mask].mean()
        bin_accuracy = y[mask].mean()
        error += (mask.sum() / total) * abs(bin_confidence - bin_accuracy)
    return float(error)
