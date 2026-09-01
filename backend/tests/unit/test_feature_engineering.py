import pytest
from ml.features.feature_definitions import FEATURE_NAMES, LEAKAGE_EXCLUDED_FIELDS

pytestmark = pytest.mark.unit

REQUIRED_FEATURES = {"failure_class", "retry_count", "historical_recovery_rate"}


def test_feature_names_is_non_empty():
    assert len(FEATURE_NAMES) > 0


def test_contracted_feature_names_present():
    # amount/attempt-history/customer-history features named explicitly in the product spec.
    assert REQUIRED_FEATURES <= set(FEATURE_NAMES)


def test_no_leakage_fields_among_features():
    assert not (set(FEATURE_NAMES) & LEAKAGE_EXCLUDED_FIELDS), (
        "A leakage-excluded field (only knowable after the outcome) appears in FEATURE_NAMES."
    )
