"""Every metric required by the product spec and docs/ml-evaluation.md, computed from a list
of outcome records produced by a benchmark run (simulator/benchmark/baseline_runner.py).
Nothing here is hand-authored into a dashboard — every value shown anywhere traces back to
one of these functions running against real (or, for the benchmark, realistic synthetic and
counterfactually-simulated) data.

Each outcome record is a dict with (at minimum): action, recovered (bool), amount (int,
paise), expected_recovery (float), intervention_cost (float), abstained (bool),
policy_rejected (bool), attempts (int). `predicted_probability` is required only for
`calibration_error`.
"""

import numpy as np


def recovered_revenue(outcomes: list[dict]) -> float:
    return float(sum(o["amount"] for o in outcomes if o.get("recovered")))


def recovery_rate(outcomes: list[dict]) -> float:
    if not outcomes:
        return 0.0
    return sum(1 for o in outcomes if o.get("recovered")) / len(outcomes)


def expected_recovery(outcomes: list[dict]) -> float:
    return float(sum(o.get("expected_recovery", 0.0) for o in outcomes))


def revenue_per_intervention(outcomes: list[dict]) -> float:
    acted = [o for o in outcomes if not o.get("abstained") and not o.get("policy_rejected")]
    if not acted:
        return 0.0
    return recovered_revenue(acted) / len(acted)


def unnecessary_action_rate(outcomes: list[dict]) -> float:
    """Fraction of executed (non-abstained, non-rejected) actions that did NOT result in
    recovery — the cost of acting on cases that were never going to recover anyway."""
    acted = [o for o in outcomes if not o.get("abstained") and not o.get("policy_rejected")]
    if not acted:
        return 0.0
    return sum(1 for o in acted if not o.get("recovered")) / len(acted)


def average_attempts(outcomes: list[dict]) -> float:
    if not outcomes:
        return 0.0
    return sum(o.get("attempts", 1) for o in outcomes) / len(outcomes)


def precision_recall_f1(outcomes: list[dict]) -> dict:
    """"Positive" = the baseline chose to act (not abstain/rejected) AND the case recovered.
    Precision: of acted-on cases, how many recovered. Recall: of all recoverable cases (by
    ground truth `recovered`), how many did the baseline act on and recover."""
    acted_and_recovered = sum(
        1 for o in outcomes if not o.get("abstained") and not o.get("policy_rejected") and o.get("recovered")
    )
    acted = sum(1 for o in outcomes if not o.get("abstained") and not o.get("policy_rejected"))
    actually_recoverable = sum(1 for o in outcomes if o.get("recovered"))

    precision = acted_and_recovered / acted if acted else 0.0
    recall = acted_and_recovered / actually_recoverable if actually_recoverable else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def calibration_error(predicted_probabilities: list[float], actual_outcomes: list[bool], n_bins: int = 10) -> float:
    if not predicted_probabilities:
        return 0.0
    probs = np.asarray(predicted_probabilities)
    actuals = np.asarray(actual_outcomes, dtype=float)
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    total = len(probs)
    error = 0.0
    for lo, hi in zip(bin_edges[:-1], bin_edges[1:], strict=True):
        upper = probs <= hi if hi >= 1.0 else probs < hi
        mask = (probs >= lo) & upper
        if not mask.any():
            continue
        error += (mask.sum() / total) * abs(probs[mask].mean() - actuals[mask].mean())
    return round(float(error), 4)


def abstention_rate(outcomes: list[dict]) -> float:
    if not outcomes:
        return 0.0
    return sum(1 for o in outcomes if o.get("abstained")) / len(outcomes)


def policy_rejection_rate(outcomes: list[dict]) -> float:
    if not outcomes:
        return 0.0
    return sum(1 for o in outcomes if o.get("policy_rejected")) / len(outcomes)


def execution_success_rate(outcomes: list[dict]) -> float:
    acted = [o for o in outcomes if not o.get("abstained") and not o.get("policy_rejected")]
    if not acted:
        return 0.0
    return sum(1 for o in acted if o.get("execution_succeeded", True)) / len(acted)


def latency_percentiles(latencies_ms: list[int]) -> dict:
    if not latencies_ms:
        return {"p50": 0.0, "p95": 0.0}
    arr = np.asarray(latencies_ms)
    return {"p50": round(float(np.percentile(arr, 50)), 2), "p95": round(float(np.percentile(arr, 95)), 2)}


def all_metrics(outcomes: list[dict], *, predicted_probabilities: list[float] | None = None) -> dict:
    """Convenience aggregator — every metric in one call, used by baseline_runner.py so each
    baseline's experiment_results rows are produced by exactly one code path."""
    metrics = {
        "recovered_revenue": recovered_revenue(outcomes),
        "recovery_rate": recovery_rate(outcomes),
        "expected_recovery": expected_recovery(outcomes),
        "revenue_per_intervention": revenue_per_intervention(outcomes),
        "unnecessary_action_rate": unnecessary_action_rate(outcomes),
        "avg_attempts": average_attempts(outcomes),
        "abstention_rate": abstention_rate(outcomes),
        "policy_rejection_rate": policy_rejection_rate(outcomes),
        "execution_success_rate": execution_success_rate(outcomes),
    }
    metrics.update({f"prf_{k}": v for k, v in precision_recall_f1(outcomes).items()})
    if predicted_probabilities is not None:
        actuals = [bool(o.get("recovered")) for o in outcomes]
        metrics["calibration_error"] = calibration_error(predicted_probabilities, actuals)
    return metrics
