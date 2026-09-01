"""Pure tests for ml/evaluation/metrics.py's Net Recovery Value and AI-ablation-specific
metrics (diagnosis_accuracy, recommended_action_agreement_rate, llm_failure_rate,
llm_latency_percentiles) — no DB, no model, no LLM. Imports across the backend/ml boundary
the same way simulator/benchmark/baseline_runner.py does (see tests/conftest.py's sys.path
setup for the monorepo convention).
"""

import pytest
from ml.evaluation.metrics import (
    ai_ablation_metrics,
    diagnosis_accuracy,
    llm_failure_rate,
    llm_latency_percentiles,
    net_recovery_value,
    recommended_action_agreement_rate,
)

pytestmark = pytest.mark.unit


def test_net_recovery_value_matches_hand_computed_total():
    outcomes = [
        # Recovered: expected_recovery=1000, cost=20, risk=5 -> net 975
        {"expected_recovery": 1000, "intervention_cost": 20, "risk_cost": 5, "recovered": True},
        # Unnecessary action (acted, didn't recover): expected_recovery=500 (was the estimate,
        # not what happened), cost=20, risk=5 -> net still expected_recovery - cost - risk =
        # 475 (the "unnecessary" cost is already the intervention_cost paid on this row, not
        # an additional penalty stacked on top).
        {"expected_recovery": 500, "intervention_cost": 20, "risk_cost": 5, "recovered": False},
        # Abstained — excluded entirely, contributes 0.
        {"expected_recovery": 800, "intervention_cost": 0, "risk_cost": 0, "abstained": True},
        # Policy-rejected — excluded entirely, contributes 0.
        {"expected_recovery": 900, "intervention_cost": 0, "risk_cost": 0, "policy_rejected": True},
    ]
    assert net_recovery_value(outcomes) == pytest.approx(975 + 475)


def test_net_recovery_value_defaults_missing_risk_cost_to_zero():
    outcomes = [{"expected_recovery": 100, "intervention_cost": 10}]
    assert net_recovery_value(outcomes) == pytest.approx(90)


def test_net_recovery_value_of_empty_list_is_zero():
    assert net_recovery_value([]) == 0.0


def test_diagnosis_accuracy_on_toy_lists():
    predicted = ["INSUFFICIENT_FUNDS", "BANK_DECLINE", "OTHER"]
    true = ["INSUFFICIENT_FUNDS", "AUTH_FAILURE", "OTHER"]
    assert diagnosis_accuracy(predicted, true) == pytest.approx(2 / 3)


def test_diagnosis_accuracy_empty_is_zero():
    assert diagnosis_accuracy([], []) == 0.0


def test_recommended_action_agreement_rate_on_toy_lists():
    ai_actions = ["SMART_RETRY", "DELAYED_RETRY", "ESCALATION"]
    optimizer_actions = ["SMART_RETRY", "SMART_RETRY", "ESCALATION"]
    assert recommended_action_agreement_rate(ai_actions, optimizer_actions) == pytest.approx(2 / 3)


def test_llm_failure_rate_counts_any_invalid_regardless_of_error_reason():
    ai_results = [
        {"is_valid": True},
        {"is_valid": False, "error": "no_api_key"},
        {"is_valid": False, "error": "call_failed:timeout"},
        {"is_valid": False, "error": "invalid_output:validation_error"},
    ]
    assert llm_failure_rate(ai_results) == pytest.approx(3 / 4)


def test_llm_failure_rate_of_empty_list_is_zero():
    assert llm_failure_rate([]) == 0.0


def test_llm_latency_percentiles_ignores_missing_latency():
    ai_results = [{"latency_ms": 100}, {"latency_ms": 200}, {"latency_ms": None}, {}]
    percentiles = llm_latency_percentiles(ai_results)
    assert percentiles["p50"] > 0
    assert percentiles["p95"] >= percentiles["p50"]


def test_ai_ablation_metrics_aggregates_everything_and_skips_invalid_rows():
    outcomes = [{"action": "SMART_RETRY"}, {"action": "DELAYED_RETRY"}]
    ai_results = [
        {
            "is_valid": True,
            "latency_ms": 150,
            "output": {"failure_class": "INSUFFICIENT_FUNDS", "recommended_action": "SMART_RETRY"},
        },
        {"is_valid": False, "latency_ms": 50, "output": None},
    ]
    true_failure_classes = ["INSUFFICIENT_FUNDS", "BANK_DECLINE"]

    metrics = ai_ablation_metrics(
        outcomes=outcomes, ai_results=ai_results, true_failure_classes=true_failure_classes
    )

    assert metrics["diagnosis_accuracy"] == pytest.approx(1.0)  # only the valid row counted
    assert metrics["recommended_action_agreement_rate"] == pytest.approx(1.0)
    assert metrics["llm_failure_rate"] == pytest.approx(0.5)
    assert "llm_latency_ms_p50" in metrics
    assert "llm_latency_ms_p95" in metrics
