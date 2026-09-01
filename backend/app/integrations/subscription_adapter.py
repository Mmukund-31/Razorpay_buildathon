"""The REAL recovery mechanism for subscriptions in `pending`/`halted` state.

Verified (docs/razorpay-integration.md §5): card/UPI auto-retry is Razorpay-managed on a
T+0..T+3 day cycle; once `halted`, the only merchant-side levers are (a) prompting the
customer through `subscription_card_change` (a hosted-page flow letting them update their
card), or (b) manually charging an `issued` invoice, which Razorpay does NOT support for
domestic cards.

Confidence note (Phase 0 honesty, not Phase 10 overreach): `fetch_subscription` below calls
the standard, well-documented `GET /v1/subscriptions/{id}` endpoint. The exact REST shape for
*triggering* `subscription_card_change` outside of the checkout.js hosted flow was not
independently re-verified byte-for-byte against a live Razorpay account during Phase 0
research — the subscription entity itself carries a `short_url` for customer-facing
management, which `request_card_change` surfaces as the actionable link. Anyone taking this
to a real production subscription-recovery flow should re-confirm this specific call against
the current Razorpay dashboard/docs before relying on it — see docs/razorpay-integration.md's
"never conflate real vs simulated" rule; this adapter does not claim more certainty than
Phase 0 actually established for this one sub-flow.
"""

from dataclasses import dataclass

from app.integrations.gateway_interface import SubscriptionGateway
from app.integrations.razorpay_client import RazorpayAPIError, RazorpayClient


@dataclass
class SubscriptionAdapter(SubscriptionGateway):
    client: RazorpayClient

    async def fetch_subscription(self, *, razorpay_subscription_id: str) -> dict:
        return await self.client.get(f"/subscriptions/{razorpay_subscription_id}")

    async def request_card_change(self, *, razorpay_subscription_id: str) -> dict:
        """Returns {"card_change_url": str}. See module docstring's confidence note."""
        subscription = await self.fetch_subscription(razorpay_subscription_id=razorpay_subscription_id)
        short_url = subscription.get("short_url")
        if not short_url:
            raise RazorpayAPIError(
                f"subscription {razorpay_subscription_id} has no short_url to share with the customer",
                retryable=False,
            )
        return {"card_change_url": short_url}

    async def charge_invoice(self, *, razorpay_invoice_id: str) -> dict:
        """Manually charges an `issued` invoice. Razorpay does not support this for domestic
        cards — callers must check the payment method before invoking this, and treat a
        rejection here as an expected, documented limitation, not a bug."""
        return await self.client.post(f"/invoices/{razorpay_invoice_id}/charge", json={})
