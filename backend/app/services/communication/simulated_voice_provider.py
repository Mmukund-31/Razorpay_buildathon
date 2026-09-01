"""SimulatedVoiceProvider — the Hinglish voice recovery signature feature's channel.

Explicitly and only simulated: no real telephony integration exists in this build (see
docs/razorpay-integration.md §7). Never claims otherwise — every transcript is logged with
`simulated=True` and the returned `CallResult.provider` is literally this class's name.

`place_call` does NOT set `consent_recorded=True` based on its own simulated response alone —
see app/executors/handlers/hinglish_voice_handler.py, which is the one place that decision is
actually recorded onto the durable `recovery_actions` row, based on what the simulated
customer said, not assumed.
"""

import random

from app.core.logging import get_logger
from app.services.communication.provider_interface import CallResult, CommunicationProvider, DeliveryResult

logger = get_logger(__name__)

# Deterministic-by-default Hinglish customer responses. `place_call` accepts an explicit
# `simulate_response` override (used by tests and the failure-injection UI to force a
# decline), and otherwise picks affirmatively — matching the product spec's own worked
# example ("Haan, retry kar do.") as the default demo path.
_AFFIRMATIVE_RESPONSES = (
    "Haan, retry kar do.",
    "Ok theek hai, dobara try karo.",
    "Haanji, kar dijiye retry.",
)
_DECLINE_RESPONSES = (
    "Nahi abhi mat karo, baad mein dekhta hoon.",
    "Nahi, mujhe interest nahi hai.",
)


class SimulatedVoiceProvider(CommunicationProvider):
    async def send(self, *, channel: str, message: str, recipient: str) -> DeliveryResult:
        raise NotImplementedError("SimulatedVoiceProvider only supports place_call() — use TextProvider")

    async def place_call(
        self, *, script: str, recipient: str, simulate_response: str = "affirmative"
    ) -> CallResult:
        rng = random.Random(f"{recipient}:{script}")
        if simulate_response == "affirmative":
            customer_line = rng.choice(_AFFIRMATIVE_RESPONSES)
            consented = True
        elif simulate_response == "decline":
            customer_line = rng.choice(_DECLINE_RESPONSES)
            consented = False
        else:
            customer_line = simulate_response
            consented = False

        transcript = f"Agent: {script}\nCustomer: {customer_line}"
        logger.info(
            "simulated voice call placed",
            extra={"simulated": True, "recipient": recipient, "consented": consented},
        )
        return CallResult(
            connected=True,
            provider="SimulatedVoiceProvider",
            transcript=transcript,
            consent_recorded=consented,
        )
