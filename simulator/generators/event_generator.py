"""Builds a single synthetic Razorpay-shaped webhook payload matching the verified real
payload shape in docs/razorpay-integration.md §3, so simulator events are byte-shape
indistinguishable from real Razorpay webhooks to `app/services/razorpay_payload_parser.py`
and everything downstream of it (ADR-004: the simulator drives the real pipeline, never a
parallel fake one).
"""

import time
import uuid
from dataclasses import dataclass


def _new_id(prefix: str) -> str:
    return f"{prefix}_sim{uuid.uuid4().hex[:16]}"


@dataclass(frozen=True, slots=True)
class SimulatedPayment:
    payment_id: str
    order_id: str
    amount: int
    currency: str
    method: str
    email: str
    contact: str
    customer_name: str


def new_simulated_payment(*, amount: int, currency: str = "INR", method: str = "upi") -> SimulatedPayment:
    suffix = uuid.uuid4().hex[:6]
    return SimulatedPayment(
        payment_id=_new_id("pay"),
        order_id=_new_id("order"),
        amount=amount,
        currency=currency,
        method=method,
        email=f"demo.customer.{suffix}@example.com",
        contact=f"+9199{suffix.zfill(8)}"[:13],
        customer_name=f"Demo Customer {suffix}",
    )


def build_payment_failed_event(
    *,
    payment: SimulatedPayment,
    error_code: str = "BAD_REQUEST_ERROR",
    error_description: str = "Payment failed",
    error_source: str = "customer",
    error_step: str = "payment_authentication",
    error_reason: str = "payment_failed",
) -> dict:
    entity = {
        "id": payment.payment_id,
        "entity": "payment",
        "order_id": payment.order_id,
        "amount": payment.amount,
        "currency": payment.currency,
        "status": "failed",
        "method": payment.method,
        "email": payment.email,
        "contact": payment.contact,
        "error_code": error_code,
        "error_description": error_description,
        "error_source": error_source,
        "error_step": error_step,
        "error_reason": error_reason,
        "notes": {"customer_name": payment.customer_name, "source": "recoveryos-simulator"},
        "created_at": int(time.time()),
    }
    return {
        "entity": "event",
        "event": "payment.failed",
        "created_at": int(time.time()),
        "contains": ["payment"],
        "payload": {"payment": {"entity": entity}},
    }


def build_payment_captured_event(*, payment: SimulatedPayment) -> dict:
    entity = {
        "id": payment.payment_id,
        "entity": "payment",
        "order_id": payment.order_id,
        "amount": payment.amount,
        "currency": payment.currency,
        "status": "captured",
        "method": payment.method,
        "email": payment.email,
        "contact": payment.contact,
        "notes": {"customer_name": payment.customer_name, "source": "recoveryos-simulator"},
        "created_at": int(time.time()),
    }
    return {
        "entity": "event",
        "event": "payment.captured",
        "created_at": int(time.time()),
        "contains": ["payment"],
        "payload": {"payment": {"entity": entity}},
    }
