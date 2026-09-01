"""CUSTOMER_NOTIFICATION — simulated informational message only (no new Payment Link), via
CommunicationProvider -> TextProvider. See docs/razorpay-integration.md §7.
"""

from app.domain.models.customer import Customer
from app.domain.models.payment import Payment
from app.domain.models.recovery_action import RecoveryAction
from app.services.communication.provider_interface import CommunicationProvider


async def handle(
    *,
    recovery_action: RecoveryAction,
    payment: Payment,
    customer: Customer | None,
    communication_provider: CommunicationProvider,
) -> dict:
    recipient = (customer.phone or customer.email) if customer else None
    message = (
        f"We noticed your payment of {payment.amount / 100:.2f} {payment.currency} didn't go "
        "through. No action is needed right now — we'll keep you posted."
    )
    result = await communication_provider.send(
        channel="sms", message=message, recipient=recipient or "unknown"
    )
    return {
        "channel": "sms",
        "message": message,
        "delivered": result.delivered,
        "provider": result.provider,
    }
