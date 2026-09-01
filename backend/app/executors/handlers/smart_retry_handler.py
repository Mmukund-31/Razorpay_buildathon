"""SMART_RETRY — REAL Razorpay call (or its simulator equivalent, per
app/integrations/gateway_factory.py): creates a fresh, exact-amount Payment Link with a short
expiry, delivered via Razorpay's own notify.sms/email. See docs/razorpay-integration.md §7 —
there is no "retry a failed payment" API, this is the actual real mechanism.
"""

from app.domain.models.customer import Customer
from app.domain.models.payment import Payment
from app.domain.models.recovery_action import RecoveryAction
from app.integrations.gateway_interface import PaymentLinkGateway

EXPIRE_BY_SECONDS = 24 * 3600


async def handle(
    *,
    recovery_action: RecoveryAction,
    payment: Payment,
    customer: Customer | None,
    payment_link_adapter: PaymentLinkGateway,
) -> dict:
    result = await payment_link_adapter.create_payment_link(
        amount=payment.amount,
        currency=payment.currency,
        reference_id=f"recoveryos-{recovery_action.id}",
        description=f"Complete your payment of {payment.amount / 100:.2f} {payment.currency}",
        customer_name=customer.name if customer else None,
        customer_email=customer.email if customer else None,
        customer_contact=customer.phone if customer else None,
        expire_by_seconds=EXPIRE_BY_SECONDS,
    )
    return {"channel": "payment_link", **result}
