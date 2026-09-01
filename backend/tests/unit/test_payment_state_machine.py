from datetime import UTC, datetime, timedelta

import pytest

from app.domain.enums import PaymentStatus
from app.domain.payment_state_machine import PaymentEvent, PaymentSnapshot, apply_event, can_transition

pytestmark = pytest.mark.unit

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def snapshot(status: PaymentStatus, *, is_terminal: bool, last_ts=None, last_seq=None) -> PaymentSnapshot:
    return PaymentSnapshot(
        status=status, is_terminal=is_terminal, last_event_created_at=last_ts, last_event_sequence_id=last_seq
    )


def event(event_type: str, *, ts=T0, seq=1) -> PaymentEvent:
    return PaymentEvent(event_type=event_type, created_at=ts, sequence_id=seq)


def test_created_to_authorized_to_captured_legal_path():
    s = snapshot(PaymentStatus.CREATED, is_terminal=False)
    r1 = apply_event(s, event("payment.authorized", ts=T0, seq=1))
    assert r1.applied and r1.new_status == PaymentStatus.AUTHORIZED and not r1.new_is_terminal

    s = snapshot(PaymentStatus.AUTHORIZED, is_terminal=False, last_ts=T0, last_seq=1)
    r2 = apply_event(s, event("payment.captured", ts=T0 + timedelta(seconds=1), seq=2))
    assert r2.applied and r2.new_status == PaymentStatus.CAPTURED and r2.new_is_terminal


def test_terminal_state_rejects_any_further_event():
    s = snapshot(PaymentStatus.CAPTURED, is_terminal=True, last_ts=T0, last_seq=1)
    r = apply_event(s, event("payment.failed", ts=T0 + timedelta(seconds=1), seq=2))
    assert not r.applied
    assert r.ignored_reason == "TERMINAL"
    assert not can_transition(s, event("payment.failed", ts=T0 + timedelta(seconds=1), seq=2))


def test_stale_event_rejected_even_though_target_would_otherwise_be_legal():
    # snapshot already advanced past this event's watermark (e.g. a delayed/out-of-order
    # delivery of an older event arriving after a newer one was already applied).
    s = snapshot(PaymentStatus.CREATED, is_terminal=False, last_ts=T0 + timedelta(seconds=10), last_seq=5)
    stale = event("payment.authorized", ts=T0, seq=1)  # older than the watermark
    r = apply_event(s, stale)
    assert not r.applied
    assert r.ignored_reason == "STALE"


def test_failed_to_captured_succeeds_upi_retry_quirk():
    s = snapshot(PaymentStatus.FAILED, is_terminal=False, last_ts=T0, last_seq=1)
    r = apply_event(s, event("payment.captured", ts=T0 + timedelta(seconds=5), seq=2))
    assert r.applied
    assert r.new_status == PaymentStatus.CAPTURED
    assert r.new_is_terminal


def test_unrecognized_event_on_non_terminal_state_degrades_to_unknown():
    s = snapshot(PaymentStatus.CREATED, is_terminal=False)
    r = apply_event(s, event("payment.dispute.created", ts=T0, seq=1))
    assert r.applied
    assert r.new_status == PaymentStatus.UNKNOWN
    assert not r.new_is_terminal
