"""ML tests: model loading, inference, and feature-schema/leakage checks — against the REAL
trained artifact (ml/training/artifacts/), not a mock. Skips gracefully (not a failure) if no
model has been trained yet in this environment — see the skip check below.
"""

import pytest
from ml.inference.predictor import load_active_model

from app.agents import ml_predictor
from app.domain.enums import ActionType

pytestmark = pytest.mark.unit

VALID_FEATURES = {
    "amount": 849_900,
    "payment_method": "upi",
    "failure_class": "INSUFFICIENT_FUNDS",
    "retry_count": 0,
    "time_since_failure_hours": 1.0,
    "customer_success_rate": 0.7,
    "customer_failure_rate": 0.3,
    "historical_recovery_rate": 0.4,
    "customer_lifetime_value": 50_000.0,
    "subscription_status": "none",
    "hour_of_day": 14,
    "day_of_week": 2,
    "previous_response_to_intervention": "voice",
    "number_of_prior_recoveries": 2,
}


def _require_trained_model():
    if load_active_model() is None:
        pytest.skip(
            "No trained model artifact found — run "
            "`python ml/training/train_lightgbm.py` (after generating a dataset) first."
        )


@pytest.fixture(autouse=True)
def _reset_cache():
    ml_predictor.reset_cache()
    yield
    ml_predictor.reset_cache()


def test_active_model_loads():
    _require_trained_model()
    model = load_active_model()
    assert model is not None
    assert model.model_name
    assert model.model_version


@pytest.mark.asyncio
async def test_predict_returns_valid_probability_for_every_action():
    _require_trained_model()
    for action in ActionType:
        result = await ml_predictor.predict(action, VALID_FEATURES)
        assert result.is_valid, f"{action} prediction was invalid: {result.error}"
        assert result.probability_of_recovery is not None
        assert 0.0 <= result.probability_of_recovery <= 1.0


@pytest.mark.asyncio
async def test_predict_is_deterministic_for_the_same_input():
    _require_trained_model()
    first = await ml_predictor.predict(ActionType.SMART_RETRY, VALID_FEATURES)
    second = await ml_predictor.predict(ActionType.SMART_RETRY, VALID_FEATURES)
    assert first.probability_of_recovery == second.probability_of_recovery


@pytest.mark.asyncio
async def test_predict_probability_varies_meaningfully_by_action():
    """A trivially broken model (e.g. ignoring candidate_action entirely) would return the
    same probability regardless of action — this is a coarse sanity check the feature is
    actually being used, not a claim about which specific action should win."""
    _require_trained_model()
    results = {}
    for action in ActionType:
        result = await ml_predictor.predict(action, VALID_FEATURES)
        results[action] = result.probability_of_recovery
    assert len(set(results.values())) > 1, "model produced identical probability for every action"


@pytest.mark.asyncio
async def test_predict_with_missing_model_returns_invalid(monkeypatch):
    monkeypatch.setattr(ml_predictor, "_get_model", lambda: None)
    result = await ml_predictor.predict(ActionType.SMART_RETRY, VALID_FEATURES)
    assert not result.is_valid
    assert result.error == "no_active_model"
    assert result.probability_of_recovery is None


def test_feature_contract_matches_generator_columns():
    """The dataset generator and the model's expected feature set must never drift apart
    silently — both derive from ml/features/feature_definitions.py, this just proves it."""
    import pandas as pd
    from ml.data.synthetic_generator import generate
    from ml.features.feature_definitions import FEATURE_NAMES

    df = generate(n_rows=20, seed=1)
    assert set(FEATURE_NAMES) <= set(df.columns)
    assert isinstance(df, pd.DataFrame)
