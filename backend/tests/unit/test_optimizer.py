import pytest

from app.domain.enums import ActionType
from app.services.optimizer_service import (
    ScoredCandidate,
    compute_expected_recovery,
    compute_expected_value,
    rank_candidates,
)

pytestmark = pytest.mark.unit


def test_compute_expected_recovery_is_probability_times_amount():
    assert compute_expected_recovery(0.5, 1000) == 500
    assert compute_expected_recovery(0.0, 1000) == 0
    assert compute_expected_recovery(1.0, 1000) == 1000


@pytest.mark.parametrize("bad_probability", [-0.01, 1.01, 2.0])
def test_compute_expected_recovery_rejects_out_of_range_probability(bad_probability):
    with pytest.raises(ValueError):
        compute_expected_recovery(bad_probability, 1000)


def test_compute_expected_value_subtracts_intervention_and_risk_cost():
    value = compute_expected_value(0.8, 1000, intervention_cost=10, risk_cost=5)
    assert value == pytest.approx(800 - 10 - 5)


def test_compute_expected_value_defaults_costs_to_zero():
    assert compute_expected_value(0.5, 1000) == 500


def test_rank_candidates_orders_by_expected_value_descending():
    low = ScoredCandidate(ActionType.NO_ACTION, 0.0, 0, 0, 0, 0)
    mid = ScoredCandidate(ActionType.SMART_RETRY, 0.5, 500, 10, 0, 490)
    high = ScoredCandidate(ActionType.HINGLISH_VOICE, 0.7, 700, 50, 0, 650)

    ranked = rank_candidates([mid, low, high])

    assert [c.action_type for c in ranked] == [
        ActionType.HINGLISH_VOICE,
        ActionType.SMART_RETRY,
        ActionType.NO_ACTION,
    ]
