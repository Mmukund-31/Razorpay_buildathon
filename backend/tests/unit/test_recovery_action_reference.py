"""Round-trip and malformed-input handling for the RecoveryAction<->Razorpay Payment Link
`reference_id` correlation key. See app/domain/recovery_action_reference.py.
"""

import uuid

import pytest

from app.domain.recovery_action_reference import build_reference_id, parse_recovery_action_id

pytestmark = pytest.mark.unit


def test_round_trips_a_real_recovery_action_id():
    action_id = uuid.uuid4()
    reference_id = build_reference_id(action_id)
    assert reference_id == f"recoveryos-{action_id}"
    assert parse_recovery_action_id(reference_id) == action_id


@pytest.mark.parametrize(
    "reference_id",
    [
        None,
        "",
        "not-ours-at-all",
        "recoveryos-not-a-uuid",
        "RECOVERYOS-" + str(uuid.uuid4()),  # wrong case prefix — not a match
        f"other-prefix-{uuid.uuid4()}",
    ],
)
def test_rejects_foreign_or_malformed_reference_ids(reference_id):
    assert parse_recovery_action_id(reference_id) is None
