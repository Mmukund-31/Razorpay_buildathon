"""CUSTOMER_ACTION_REQUEST — hybrid: a REAL Payment Link call plus a simulated explanatory
message describing what the customer must fix. See docs/razorpay-integration.md §7.
"""

from app.domain.models.customer import Customer
from app.domain.models.payment import Payment
from app.domain.models.recovery_action import RecoveryAction
from app.executors.handlers import smart_retry_handler
from app.integrations.gateway_interface import PaymentLinkGateway
from app.services.communication.provider_interface import CommunicationProvider


async def handle(
    *,
    recovery_action: RecoveryAction,
    payment: Payment,
    customer: Customer | None,
    payment_link_adapter: PaymentLinkGateway,
    communication_provider: CommunicationProvider,
) -> dict:
    link_result = await smart_retry_handler.handle(
        recovery_action=recovery_action,
        payment=payment,
        customer=customer,
        payment_link_adapter=payment_link_adapter,
    )

    recipient = (customer.phone or customer.email) if customer else None
    message = (
        f"Your payment of {payment.amount / 100:.2f} {payment.currency} needs your attention "
        f"— please check your payment details and complete it here: {link_result['short_url']}"
    )
    delivery = await communication_provider.send(
        channel="sms", message=message, recipient=recipient or "unknown"
    )
    return {
        "channel": "payment_link+sms",
        "message": message,
        "delivered": delivery.delivered,
        **{k: v for k, v in link_result.items() if k != "channel"},
    }
