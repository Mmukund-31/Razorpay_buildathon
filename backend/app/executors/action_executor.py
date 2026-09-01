"""ActionExecutor — the ONLY module allowed to import the Razorpay adapters or
CommunicationProvider implementations (see docs/architecture.md's execution boundary rule).

Dispatch is strictly on the 7-value `ActionType` enum via a dict built once at construction —
never an if/elif chain that could silently fall through to an unhandled action type. Every
handler receives the already-persisted `RecoveryAction` row (so it can read
`policy_evaluation_id`, `idempotency_key`, etc.) plus the `Payment`/`Customer` it concerns,
and returns a plain result dict that `app/services/execution_service.py` stores verbatim on
`recovery_actions.result`.

The executor never reads or sets `amount` — it always comes from `payment.amount`, immutable
at execution time.
"""

from dataclasses import dataclass

from app.domain.enums import ActionType
from app.domain.models.customer import Customer
from app.domain.models.payment import Payment
from app.domain.models.recovery_action import RecoveryAction
from app.executors.handlers import (
    customer_action_request_handler,
    customer_notification_handler,
    delayed_retry_handler,
    escalation_handler,
    hinglish_voice_handler,
    no_action_handler,
    smart_retry_handler,
)
from app.integrations.gateway_interface import PaymentLinkGateway, SubscriptionGateway
from app.services.communication.provider_interface import CommunicationProvider


class UnknownActionType(Exception):
    """Raised if `action.action_type` isn't one of the 7 allowlisted values — should be
    unreachable given the DB CHECK constraint and Pydantic enum validation upstream, but the
    executor checks anyway rather than trusting either of those alone."""


@dataclass
class ActionExecutor:
    payment_link_adapter: PaymentLinkGateway
    subscription_adapter: SubscriptionGateway
    communication_provider: CommunicationProvider

    def __post_init__(self) -> None:
        self._dispatch = {
            ActionType.SMART_RETRY: self._smart_retry,
            ActionType.DELAYED_RETRY: self._delayed_retry,
            ActionType.CUSTOMER_NOTIFICATION: self._customer_notification,
            ActionType.CUSTOMER_ACTION_REQUEST: self._customer_action_request,
            ActionType.HINGLISH_VOICE: self._hinglish_voice,
            ActionType.ESCALATION: self._escalation,
            ActionType.NO_ACTION: self._no_action,
        }

    async def execute(self, action: RecoveryAction, payment: Payment, customer: Customer | None) -> dict:
        try:
            action_type = ActionType(action.action_type)
        except ValueError as exc:
            raise UnknownActionType(action.action_type) from exc

        handler = self._dispatch.get(action_type)
        if handler is None:
            raise UnknownActionType(action.action_type)
        return await handler(action, payment, customer)

    async def _smart_retry(self, action: RecoveryAction, payment: Payment, customer: Customer | None) -> dict:
        return await smart_retry_handler.handle(
            recovery_action=action,
            payment=payment,
            customer=customer,
            payment_link_adapter=self.payment_link_adapter,
        )

    async def _delayed_retry(
        self, action: RecoveryAction, payment: Payment, customer: Customer | None
    ) -> dict:
        return await delayed_retry_handler.handle(
            recovery_action=action,
            payment=payment,
            customer=customer,
            payment_link_adapter=self.payment_link_adapter,
        )

    async def _customer_notification(
        self, action: RecoveryAction, payment: Payment, customer: Customer | None
    ) -> dict:
        return await customer_notification_handler.handle(
            recovery_action=action,
            payment=payment,
            customer=customer,
            communication_provider=self.communication_provider,
        )

    async def _customer_action_request(
        self, action: RecoveryAction, payment: Payment, customer: Customer | None
    ) -> dict:
        return await customer_action_request_handler.handle(
            recovery_action=action,
            payment=payment,
            customer=customer,
            payment_link_adapter=self.payment_link_adapter,
            communication_provider=self.communication_provider,
        )

    async def _hinglish_voice(
        self, action: RecoveryAction, payment: Payment, customer: Customer | None
    ) -> dict:
        return await hinglish_voice_handler.handle(
            recovery_action=action,
            payment=payment,
            customer=customer,
            communication_provider=self.communication_provider,
        )

    async def _escalation(self, action: RecoveryAction, payment: Payment, customer: Customer | None) -> dict:
        return await escalation_handler.handle(recovery_action=action, payment=payment, customer=customer)

    async def _no_action(self, action: RecoveryAction, payment: Payment, customer: Customer | None) -> dict:
        return no_action_handler.handle(reason="optimizer/policy selected NO_ACTION")
