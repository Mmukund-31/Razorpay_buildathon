"""The interface HINGLISH_VOICE is selected *through*, not bolted onto — the recovery
decision engine (optimizer + policy) picks an ActionType, and the executor resolves it to a
CommunicationProvider call exactly like every other action. See docs/razorpay-integration.md
for why voice and plain notifications are simulated rather than backed by real telephony/SMS
in this build, and why that's stated honestly rather than implied otherwise.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    delivered: bool
    provider: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class CallResult:
    connected: bool
    provider: str
    transcript: str | None = None
    consent_recorded: bool = False


class CommunicationProvider(ABC):
    @abstractmethod
    async def send(self, *, channel: str, message: str, recipient: str) -> DeliveryResult: ...

    @abstractmethod
    async def place_call(
        self, *, script: str, recipient: str, simulate_response: str = "affirmative"
    ) -> CallResult:
        """`simulate_response` is honored by simulated providers ("affirmative" | "decline" |
        a literal customer line) and ignored by a real telephony provider, which has no way
        to script what a real customer says — kept on the shared interface anyway so callers
        (tests, the failure-injection UI) don't need to know which kind of provider they hold.
        """
        ...
