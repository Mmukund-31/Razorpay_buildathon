"""DELAYED_RETRY — identical mechanism to SMART_RETRY, fired by the background worker once
`recovery_actions.scheduled_for` is reached (the case sits in SCHEDULED until then — see
app/services/execution_service.py). Delegates to smart_retry_handler rather than duplicating
the Payment Link creation logic.
"""

from app.domain.models.customer import Customer
from app.domain.models.payment import Payment
from app.domain.models.recovery_action import RecoveryAction
from app.executors.handlers import smart_retry_handler
from app.integrations.gateway_interface import PaymentLinkGateway


async def handle(
    *,
    recovery_action: RecoveryAction,
    payment: Payment,
    customer: Customer | None,
    payment_link_adapter: PaymentLinkGateway,
) -> dict:
    return await smart_retry_handler.handle(
        recovery_action=recovery_action,
        payment=payment,
        customer=customer,
        payment_link_adapter=payment_link_adapter,
    )
