"""Every metric required by the product spec and docs/ml-evaluation.md, computed from a list
of outcome records produced by a benchmark run (simulator/benchmark/baseline_runner.py).
Nothing here is hand-authored into a dashboard — every value shown anywhere traces back to
one of these functions running against real (or, for the benchmark, realistic synthetic and
counterfactually-simulated) data.

Each outcome record is a dict with (at minimum): action, recovered (bool), amount (int,
paise), expected_recovery (float), intervention_cost (float), abstained (bool),
policy_rejected (bool), attempts (int). `risk_cost` (float) is required only for
`net_recovery_value`; `predicted_probability` is required only for `calibration_error`.
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


def net_recovery_value(outcomes: list[dict]) -> float:
    """Expected Recovered Revenue - Intervention Cost - Risk Cost - Unnecessary Action Cost,
    summed across outcomes — the objective the task asks the optimizer to actually pursue,
    instead of maximum gross recovered amount alone (see docs/ai-ablation.md and
    docs/ml-evaluation.md's gross-vs-net framing). "Unnecessary action cost" is the
    intervention cost paid on cases that were acted on but did NOT recover — money spent for
    nothing, counted once here (not double-counted on top of `intervention_cost`, which
    already includes it economically; this metric is the fully-loaded net figure, not an
    additive stack of overlapping costs).
    """
    total = 0.0
    for o in outcomes:
        if o.get("abstained") or o.get("policy_rejected"):
            continue
        expected_recovery = o.get("expected_recovery", 0.0)
        intervention_cost = o.get("intervention_cost", 0.0)
        risk_cost = o.get("risk_cost", 0.0)
        total += expected_recovery - intervention_cost - risk_cost
    return float(total)


def diagnosis_accuracy(predicted_failure_classes: list[str], true_failure_classes: list[str]) -> float:
    """Fraction where the AI's stated failure_class matches the row's actual (synthetic
    ground-truth) failure_class. Both lists must already be filtered to rows where the AI
    produced a valid diagnosis — this is a real accuracy metric, not an agreement-with-ML one."""
    if not predicted_failure_classes:
        return 0.0
    matches = sum(
        1 for p, t in zip(predicted_failure_classes, true_failure_classes, strict=True) if p == t
    )
    return matches / len(predicted_failure_classes)


def recommended_action_agreement_rate(ai_actions: list[str], optimizer_actions: list[str]) -> float:
    """Fraction of rows where the AI's recommended_action matches the action the optimizer
    ultimately chose (post-nudge) — NOT ground truth. Measures how much the AI's opinion and
    the deterministic EV-argmax already agree, i.e. how much genuine influence the bounded
    nudge (app/services/analysis_service.py's _AI_NUDGE_MAX_FRACTION) actually has."""
    if not ai_actions:
        return 0.0
    matches = sum(1 for a, o in zip(ai_actions, optimizer_actions, strict=True) if a == o)
    return matches / len(ai_actions)


def llm_failure_rate(ai_results: list[dict]) -> float:
    """Fraction of AI diagnostician calls that did not return a valid, schema-conforming
    result — `is_valid=False` for any reason (no_api_key, circuit_open, invalid_output,
    call_failed). Mirrors app.agents.ai_diagnostician.AIDiagnosisResult.is_valid exactly, no
    reinterpretation of what counts as a failure."""
    if not ai_results:
        return 0.0
    return sum(1 for r in ai_results if not r.get("is_valid")) / len(ai_results)


def llm_latency_percentiles(ai_results: list[dict]) -> dict:
    return latency_percentiles([r["latency_ms"] for r in ai_results if r.get("latency_ms") is not None])


def ai_ablation_metrics(
    *, outcomes: list[dict], ai_results: list[dict], true_failure_classes: list[str]
) -> dict:
    """Every AI-specific metric the ablation study needs, in one call — kept separate from
    `all_metrics()` because these require extra per-row inputs (`ai_results`,
    `true_failure_classes`) that no other baseline has."""
    ai_predicted_classes = [
        r["output"]["failure_class"] if r.get("is_valid") and r.get("output") else None for r in ai_results
    ]
    ai_actions = [
        r["output"]["recommended_action"] if r.get("is_valid") and r.get("output") else None
        for r in ai_results
    ]
    chosen_actions = [o["action"] for o in outcomes]

    valid_pairs = [
        (p, t) for p, t in zip(ai_predicted_classes, true_failure_classes, strict=True) if p is not None
    ]
    agreement_pairs = [
        (a, c) for a, c in zip(ai_actions, chosen_actions, strict=True) if a is not None
    ]

    return {
        "diagnosis_accuracy": diagnosis_accuracy(
            [p for p, _ in valid_pairs], [t for _, t in valid_pairs]
        ),
        "recommended_action_agreement_rate": recommended_action_agreement_rate(
            [a for a, _ in agreement_pairs], [c for _, c in agreement_pairs]
        ),
        "llm_failure_rate": llm_failure_rate(ai_results),
        **{f"llm_latency_ms_{k}": v for k, v in llm_latency_percentiles(ai_results).items()},
    }


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
        "net_recovery_value": net_recovery_value(outcomes),
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
