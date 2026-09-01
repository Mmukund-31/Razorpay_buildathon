"""Composition point: decides whether the real Razorpay-backed adapters or the simulator
adapters get wired into `ActionExecutor`. Real credentials present -> real adapters; missing
-> simulator, loudly logged once at startup so it's never a silent surprise which mode a
deployment is running in. This is the ONE place that decision is made — see
docs/razorpay-integration.md §8 and docs/decisions.md ADR-004.
"""

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.integrations.gateway_interface import PaymentLinkGateway, SubscriptionGateway
from app.integrations.payment_link_adapter import PaymentLinkAdapter
from app.integrations.razorpay_client import RazorpayClient
from app.integrations.simulator_gateway import SimulatorPaymentLinkAdapter, SimulatorSubscriptionAdapter
from app.integrations.subscription_adapter import SubscriptionAdapter

logger = get_logger(__name__)


def _has_real_credentials(settings: Settings) -> bool:
    return bool(settings.razorpay_key_id and settings.razorpay_key_secret)


def get_payment_link_gateway(settings: Settings | None = None) -> PaymentLinkGateway:
    settings = settings or get_settings()
    if _has_real_credentials(settings):
        return PaymentLinkAdapter(client=RazorpayClient.from_settings(settings))
    logger.info("RAZORPAY_KEY_ID/SECRET not configured — using SimulatorPaymentLinkAdapter")
    return SimulatorPaymentLinkAdapter()


def get_subscription_gateway(settings: Settings | None = None) -> SubscriptionGateway:
    settings = settings or get_settings()
    if _has_real_credentials(settings):
        return SubscriptionAdapter(client=RazorpayClient.from_settings(settings))
    logger.info("RAZORPAY_KEY_ID/SECRET not configured — using SimulatorSubscriptionAdapter")
    return SimulatorSubscriptionAdapter()
