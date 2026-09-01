"""Pure parsing tests for app/services/razorpay_payload_parser.py — no DB needed. Covers the
plain payment.failed/payment.captured shape (regression) and the payment_link.paid shape
(payload.payment_link.entity alongside payload.payment.entity), verified against
razorpay.com/docs — see docs/razorpay-integration.md's payment-link correlation section.
"""

import pytest

from app.services.razorpay_payload_parser import derive_failure_class, parse_payment_entity

pytestmark = pytest.mark.unit


def test_plain_payment_captured_has_no_payment_link_fields():
    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_ABC123",
                    "order_id": "order_XYZ",
                    "amount": 849900,
                    "currency": "INR",
                    "method": "upi",
                    "notes": {"customer_name": "Asha"},
                }
            }
        },
    }
    parsed = parse_payment_entity(payload)
    assert parsed is not None
    assert parsed.razorpay_payment_id == "pay_ABC123"
    assert parsed.customer_name == "Asha"
    assert parsed.payment_link_id is None
    assert parsed.payment_link_reference_id is None
    assert parsed.notes == {"customer_name": "Asha"}


def test_payment_link_paid_carries_both_entities():
    payload = {
        "event": "payment_link.paid",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_DEF456",
                    "reference_id": "recoveryos-11111111-1111-1111-1111-111111111111",
                    "notes": {"source": "recoveryos"},
                }
            },
            "payment": {
                "entity": {
                    "id": "pay_NEW789",
                    "order_id": "order_NEW",
                    "amount": 1499900,
                    "currency": "INR",
                    "method": "card",
                }
            },
        },
    }
    parsed = parse_payment_entity(payload)
    assert parsed is not None
    assert parsed.razorpay_payment_id == "pay_NEW789"
    assert parsed.amount == 1499900
    assert parsed.payment_link_id == "plink_DEF456"
    assert parsed.payment_link_reference_id == "recoveryos-11111111-1111-1111-1111-111111111111"


def test_no_payment_entity_returns_none():
    assert parse_payment_entity({"event": "subscription.charged", "payload": {}}) is None


def test_missing_notes_does_not_crash():
    payload = {"payload": {"payment": {"entity": {"id": "pay_1", "amount": 100, "currency": "INR"}}}}
    parsed = parse_payment_entity(payload)
    assert parsed is not None
    assert parsed.notes is None
    assert parsed.customer_name is None


@pytest.mark.parametrize(
    "reason,code,expected",
    [
        ("insufficient funds", None, "INSUFFICIENT_FUNDS"),
        (None, "BAD_OTP_ATTEMPTS", "AUTH_FAILURE"),
        ("gateway_timeout", None, "GATEWAY_TIMEOUT"),
        ("issuer_declined", None, "BANK_DECLINE"),
        ("network_error", None, "NETWORK_ERROR"),
        ("payment_blocked_risk", None, "RISK_BLOCKED"),
        ("something_unmapped", None, "OTHER"),
        (None, None, None),
    ],
)
def test_derive_failure_class(reason, code, expected):
    assert derive_failure_class(reason, code) == expected
