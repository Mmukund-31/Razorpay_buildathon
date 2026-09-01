"""TextProvider — simulated SMS/email delivery for CUSTOMER_NOTIFICATION and the messaging
half of CUSTOMER_ACTION_REQUEST. `place_call` is not supported by this provider (raises) —
voice always goes through SimulatedVoiceProvider, enforced by type, not convention.

Deliberately simulated (logged, not sent) in this build — see
docs/razorpay-integration.md §7 for why, and TextProvider is the seam a real SMS/email
gateway would plug into later without touching any caller.
"""

from app.core.logging import get_logger
from app.services.communication.provider_interface import CallResult, CommunicationProvider, DeliveryResult

logger = get_logger(__name__)


class TextProvider(CommunicationProvider):
    async def send(self, *, channel: str, message: str, recipient: str) -> DeliveryResult:
        logger.info(
            "simulated text delivery",
            extra={
                "simulated": True,
                "channel": channel,
                "recipient": recipient,
                "message_length": len(message),
            },
        )
        return DeliveryResult(delivered=True, provider="TextProvider", detail=f"simulated {channel}")

    async def place_call(
        self, *, script: str, recipient: str, simulate_response: str = "affirmative"
    ) -> CallResult:
        raise NotImplementedError("TextProvider does not support voice — use SimulatedVoiceProvider")
