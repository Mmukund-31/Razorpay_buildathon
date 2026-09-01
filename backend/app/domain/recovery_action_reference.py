"""The correlation key between a RecoveryAction and the Razorpay Payment Link created for
it, and back again.

`reference_id` is a Razorpay Payment Link field (POST /v1/payment_links, verified in
docs/razorpay-integration.md §4) that RecoveryOS sets on creation and Razorpay returns
unchanged on `payload.payment_link.entity.reference_id` in the `payment_link.paid` webhook
(verified against razorpay.com/docs — see docs/razorpay-integration.md's payment-link
correlation section). Round-tripping it through one shared pair of functions means the
producer (app/executors/handlers/smart_retry_handler.py) and the consumer
(app/services/outcome_service.py) can never drift out of sync on the format.
"""

import uuid

_PREFIX = "recoveryos-"


def build_reference_id(recovery_action_id: uuid.UUID) -> str:
    return f"{_PREFIX}{recovery_action_id}"


def parse_recovery_action_id(reference_id: str | None) -> uuid.UUID | None:
    """Returns None for anything that isn't a well-formed RecoveryOS reference id — a
    reference_id RecoveryOS didn't create (e.g. a merchant's other payment links, if any
    share the same webhook), a stale/foreign value, or an absent field. Never raises: this
    parses untrusted, Razorpay-echoed input, not our own known-good output."""
    if not reference_id or not reference_id.startswith(_PREFIX):
        return None
    try:
        return uuid.UUID(reference_id.removeprefix(_PREFIX))
    except ValueError:
        return None
