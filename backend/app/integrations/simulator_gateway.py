"""Fake `PaymentLinkGateway`/`SubscriptionGateway` implementations used when real Razorpay
credentials aren't configured, and always used by the synthetic benchmark pipeline
(docs/razorpay-integration.md §8's "never conflate real vs simulated" rule). Every generated
id/url is prefixed `sim_`/`https://rzp.io/sim/...` so it can never be mistaken for a real
Razorpay identifier, and every call is logged at INFO with `simulated=True` explicitly in the
structured fields — nothing about this class pretends to be the real adapter.
"""

import time
import uuid

from app.core.logging import get_logger
from app.integrations.gateway_interface import PaymentLinkGateway, SubscriptionGateway

logger = get_logger(__name__)


class SimulatorPaymentLinkAdapter(PaymentLinkGateway):
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
    ) -> dict:
        link_id = f"sim_plink_{uuid.uuid4().hex[:14]}"
        logger.info(
            "simulated payment link created",
            extra={
                "simulated": True,
                "razorpay_payment_link_id": link_id,
                "amount": amount,
                "reference_id": reference_id,
                "expire_by": int(time.time()) + expire_by_seconds,
            },
        )
        return {
            "razorpay_payment_link_id": link_id,
            "short_url": f"https://rzp.io/sim/{link_id}",
            "status": "created",
        }


class SimulatorSubscriptionAdapter(SubscriptionGateway):
    async def request_card_change(self, *, razorpay_subscription_id: str) -> dict:
        url = f"https://rzp.io/sim/card-change/{razorpay_subscription_id}"
        logger.info(
            "simulated card-change link generated",
            extra={"simulated": True, "razorpay_subscription_id": razorpay_subscription_id},
        )
        return {"card_change_url": url}

    async def charge_invoice(self, *, razorpay_invoice_id: str) -> dict:
        logger.info(
            "simulated invoice charge",
            extra={"simulated": True, "razorpay_invoice_id": razorpay_invoice_id},
        )
        return {"status": "simulated_charged", "razorpay_invoice_id": razorpay_invoice_id}
