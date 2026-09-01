"""The REAL recovery mechanism for one-time payments: Razorpay has no "retry a failed
payment" API, so SMART_RETRY / DELAYED_RETRY / CUSTOMER_ACTION_REQUEST all resolve to
creating a fresh Payment Link (verified params below) and letting Razorpay deliver it.

Confirmed request/response shape (docs/razorpay-integration.md, sourced from
POST /v1/payment_links): amount, currency, reference_id, description, customer.{name,email,
contact}, notify.{sms,email} (Razorpay sends these itself), expire_by, callback_url,
callback_method, notes. Response: id (`plink_...`), short_url, status.
"""

import time
from dataclasses import dataclass

from app.integrations.gateway_interface import PaymentLinkGateway
from app.integrations.razorpay_client import RazorpayClient


@dataclass
class PaymentLinkAdapter(PaymentLinkGateway):
    client: RazorpayClient

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
        """Returns {"razorpay_payment_link_id": str, "short_url": str, "status": str}."""
        payload: dict = {
            "amount": amount,
            "currency": currency,
            "reference_id": reference_id,
            "description": description,
            "notify": {"sms": notify_sms, "email": notify_email},
            "expire_by": int(time.time()) + expire_by_seconds,
            "notes": {"source": "recoveryos"},
        }
        customer: dict = {}
        if customer_name:
            customer["name"] = customer_name
        if customer_email:
            customer["email"] = customer_email
        if customer_contact:
            customer["contact"] = customer_contact
        if customer:
            payload["customer"] = customer

        response = await self.client.post("/payment_links", json=payload)
        return {
            "razorpay_payment_link_id": response["id"],
            "short_url": response["short_url"],
            "status": response["status"],
        }
