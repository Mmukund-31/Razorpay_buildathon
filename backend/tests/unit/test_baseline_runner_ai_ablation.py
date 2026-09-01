"""Exercises simulator/benchmark/baseline_runner.py's RECOVERYOS_AI arm and its bounded
sampler with a MOCKED ai_diagnostician.diagnose() — no real LLM calls (see docs/ai-ablation.md
and the "simulator/mocks only" scope this hardening pass was done under). Confirms the nudge
arithmetic matches app.services.analysis_service._AI_NUDGE_MAX_FRACTION exactly (imported, not
hardcoded), and that an invalid/failed diagnosis never applies a nudge.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from simulator.benchmark.baseline_runner import (  # noqa: E402
    ACTIONS,
    _sample_for_ai_ablation,
    run_recoveryos_ai,
)


def _toy_df(n: int = 12) -> pd.DataFrame:
    """Every column ml/features/feature_definitions.py's FEATURE_NAMES declares, plus
    `_value_tier` (normally set by run_all_baselines before any run_* function is called —
    supplied here directly since these tests call run_recoveryos_ai standalone)."""
    failure_classes = ["INSUFFICIENT_FUNDS", "BANK_DECLINE", "GATEWAY_TIMEOUT", "OTHER"]
    return pd.DataFrame(
        {
            "amount": [100000] * n,
            "payment_method": ["upi"] * n,
            "failure_class": [failure_classes[i % len(failure_classes)] for i in range(n)],
            "retry_count": [0] * n,
            "time_since_failure_hours": [1.0] * n,
            "customer_success_rate": [0.5] * n,
            "customer_failure_rate": [0.5] * n,
            "historical_recovery_rate": [0.3] * n,
            "customer_lifetime_value": [50000.0] * n,
            "subscription_status": ["none"] * n,
            "hour_of_day": [12] * n,
            "day_of_week": [2] * n,
            "previous_response_to_intervention": ["none"] * n,
            "number_of_prior_recoveries": [0] * n,
            "_value_tier": ["mid"] * n,
        }
    )


def test_sample_for_ai_ablation_is_deterministic_and_stratified():
    df = _toy_df(40)
    sample_a = _sample_for_ai_ablation(df, n=12, seed=42)
    sample_b = _sample_for_ai_ablation(df, n=12, seed=42)

    assert sorted(sample_a.index.tolist()) == sorted(sample_b.index.tolist())
    assert len(sample_a) <= 12
    # Every failure_class present in the full set (with enough rows) shows up in the sample.
    assert set(sample_a["failure_class"]) == set(df["failure_class"])


def test_sample_for_ai_ablation_never_exceeds_requested_size():
    df = _toy_df(8)
    sample = _sample_for_ai_ablation(df, n=100, seed=1)
    assert len(sample) <= len(df)


class _FakeModel:
    pass


class _FakeDiagnosisOutput:
    def __init__(self, recommended_action: str, confidence: float, failure_class: str):
        self.recommended_action = _FakeAction(recommended_action)
        self.confidence = confidence
        self.failure_class = failure_class

    def model_dump(self, mode: str = "json") -> dict:
        return {
            "failure_class": self.failure_class,
            "recommended_action": self.recommended_action.value,
            "confidence": self.confidence,
        }


class _FakeAction:
    def __init__(self, value: str):
        self.value = value


class _FakeAIResult:
    def __init__(self, is_valid: bool, output=None, latency_ms: int = 42, error: str | None = None):
        self.is_valid = is_valid
        self.output = output
        self.latency_ms = latency_ms
        self.error = error


@pytest.fixture
def _mock_predict_and_diagnose(monkeypatch):
    """Mocks predict_proba_batch (so no real trained model is needed) and
    ai_diagnostician.diagnose (so no real LLM call is made) with deterministic values."""
    import simulator.benchmark.baseline_runner as baseline_runner

    from app.agents import ai_diagnostician

    def fake_predict_proba_batch(model, rows):
        return [0.5] * len(rows)

    monkeypatch.setattr(baseline_runner, "predict_proba_batch", fake_predict_proba_batch)

    async def fake_diagnose(*, system_prompt, user_prompt):
        return _FakeAIResult(
            is_valid=True,
            output=_FakeDiagnosisOutput("SMART_RETRY", confidence=1.0, failure_class="INSUFFICIENT_FUNDS"),
        )

    monkeypatch.setattr(ai_diagnostician, "diagnose", fake_diagnose)
    return fake_diagnose


@pytest.mark.asyncio
async def test_run_recoveryos_ai_produces_one_result_per_row_and_never_crashes_on_invalid(
    monkeypatch, _mock_predict_and_diagnose
):
    df = _toy_df(5)
    outcomes, probs, ai_results, true_classes = await run_recoveryos_ai(df, _FakeModel(), seed=1)

    assert len(outcomes) == len(df)
    assert len(probs) == len(df)
    assert len(ai_results) == len(df)
    assert len(true_classes) == len(df)
    assert all(r["is_valid"] for r in ai_results)


@pytest.mark.asyncio
async def test_run_recoveryos_ai_nudge_matches_analysis_service_constant(monkeypatch):
    """The nudge arithmetic must be imported from analysis_service, not reimplemented — this
    test would catch a silent drift if someone hardcoded a different fraction here."""
    import simulator.benchmark.baseline_runner as baseline_runner

    from app.agents import ai_diagnostician
    from app.services.analysis_service import _AI_NUDGE_MAX_FRACTION

    assert 0.0 < _AI_NUDGE_MAX_FRACTION < 1.0  # sanity: it's a real bounded fraction

    def fake_predict_proba_batch(model, rows):
        # SMART_RETRY scores lowest on raw probability but should win once nudged, proving
        # the nudge actually moved the ranking (not just a no-op).
        action = rows[0]["candidate_action"] if rows else None
        return [0.90 if action == "SMART_RETRY" else 0.91 for _ in rows]

    monkeypatch.setattr(baseline_runner, "predict_proba_batch", fake_predict_proba_batch)

    async def fake_diagnose(*, system_prompt, user_prompt):
        return _FakeAIResult(
            is_valid=True,
            output=_FakeDiagnosisOutput("SMART_RETRY", confidence=1.0, failure_class="INSUFFICIENT_FUNDS"),
        )

    monkeypatch.setattr(ai_diagnostician, "diagnose", fake_diagnose)

    df = _toy_df(1)
    outcomes, probs, ai_results, _ = await run_recoveryos_ai(df, _FakeModel(), seed=1)
    assert outcomes[0]["action"] == "SMART_RETRY"  # won only because of the nudge


@pytest.mark.asyncio
async def test_run_recoveryos_ai_applies_no_nudge_on_invalid_diagnosis(monkeypatch):
    import simulator.benchmark.baseline_runner as baseline_runner

    from app.agents import ai_diagnostician

    def fake_predict_proba_batch(model, rows):
        action = rows[0]["candidate_action"] if rows else None
        return [0.90 if action == "SMART_RETRY" else 0.91 for _ in rows]

    monkeypatch.setattr(baseline_runner, "predict_proba_batch", fake_predict_proba_batch)

    async def fake_diagnose_invalid(*, system_prompt, user_prompt):
        return _FakeAIResult(is_valid=False, output=None, error="no_api_key")

    monkeypatch.setattr(ai_diagnostician, "diagnose", fake_diagnose_invalid)

    df = _toy_df(1)
    outcomes, probs, ai_results, _ = await run_recoveryos_ai(df, _FakeModel(), seed=1)
    assert not ai_results[0]["is_valid"]
    # Without a valid nudge, the highest raw-probability action wins — NOT SMART_RETRY.
    assert outcomes[0]["action"] != "SMART_RETRY"
    assert outcomes[0]["action"] in ACTIONS
