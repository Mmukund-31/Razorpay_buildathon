"""The `PaymentGateway` interface the product spec asks for (section 26): a shared shape
both `PaymentLinkAdapter`/`SubscriptionAdapter` (real Razorpay, app/integrations/) and their
simulator counterparts (app/integrations/simulator_gateway.py) implement, so
`ActionExecutor` and everything above it never needs to know or care which one it was handed.
This is the concrete mechanism behind ADR-004 ("the simulator drives the real pipeline
through a fake adapter implementing the same interface, never a parallel fake logic path").
"""

from abc import ABC, abstractmethod


class PaymentLinkGateway(ABC):
    @abstractmethod
    async def create_payment_link(
        self,
        *,
        amount: int,
        currency: str,
        reference_id: str,
        description: str,
        customer_name: str | None,
        customer_email: str | None,
        customer_contact: str | None,
        expire_by_seconds: int,
        notify_sms: bool = True,
        notify_email: bool = True,
    ) -> dict: ...


class SubscriptionGateway(ABC):
    @abstractmethod
    async def request_card_change(self, *, razorpay_subscription_id: str) -> dict: ...

    @abstractmethod
    async def charge_invoice(self, *, razorpay_invoice_id: str) -> dict: ...
