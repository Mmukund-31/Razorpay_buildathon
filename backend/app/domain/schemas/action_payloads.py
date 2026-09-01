"""Per-ActionType payload/result shapes for `recovery_actions.payload` / `.result` JSONB
columns. Kept as explicit Pydantic models (rather than a loose dict) so
app/executors/action_executor.py (Phase 9) can validate what it's about to store before
writing it, matching the same "validate before it becomes durable state" discipline used for
AI output and policy decisions.
"""

from pydantic import BaseModel, ConfigDict


class PaymentLinkActionPayload(BaseModel):
    """SMART_RETRY / DELAYED_RETRY / the payment-link half of CUSTOMER_ACTION_REQUEST."""

    model_config = ConfigDict(extra="forbid")

    amount: int
    currency: str
    expire_by_seconds: int
    notify_sms: bool
    notify_email: bool


class PaymentLinkActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    razorpay_payment_link_id: str
    short_url: str
    status: str


class CommunicationActionPayload(BaseModel):
    """CUSTOMER_NOTIFICATION / the messaging half of CUSTOMER_ACTION_REQUEST / HINGLISH_VOICE."""

    model_config = ConfigDict(extra="forbid")

    channel: str  # sms | email | voice
    message: str
    language: str = "en"


class CommunicationActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivered: bool
    provider: str  # e.g. "SimulatedVoiceProvider"
    transcript: str | None = None


class EscalationActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
    severity: str = "medium"


class NoActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
