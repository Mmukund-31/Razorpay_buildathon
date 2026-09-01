"""HINGLISH_VOICE — the signature feature. Simulated only (CommunicationProvider ->
SimulatedVoiceProvider). REQUIRES `recovery_actions.consent_recorded=true` as a hard
precondition checked HERE — a second, independent layer beyond
app/domain/recovery_case_state_machine.py's BEGIN_EXECUTION + CONSENT_REQUIRED guard and
app/policies/rules.py's `consent_required_but_missing` rule. Three layers agreeing is the
point: this action must never dispatch without consent, and no single bug should be able to
make that happen.

The script is a deterministic, scenario-driven Hinglish template — not free-form LLM
generation (the LLM boundary in docs/architecture.md keeps the diagnostician out of anything
customer-facing that could be executed without review).
"""

from app.domain.models.customer import Customer
from app.domain.models.payment import Payment
from app.domain.models.recovery_action import RecoveryAction
from app.services.communication.provider_interface import CommunicationProvider


class ConsentNotRecorded(Exception):
    pass


def build_script(*, customer_name: str | None, amount: int, currency: str) -> str:
    name = customer_name or "aap"
    rupees = amount / 100
    return (
        f"Hi {name}, aapka {rupees:.0f} {currency} ka payment complete nahi ho paya. "
        "Agar aap chahein toh main aapko secure retry ka option bhej sakta hoon. "
        "Kya main retry kar doon?"
    )


async def handle(
    *,
    recovery_action: RecoveryAction,
    payment: Payment,
    customer: Customer | None,
    communication_provider: CommunicationProvider,
) -> dict:
    if not recovery_action.consent_recorded:
        raise ConsentNotRecorded(
            f"recovery_action {recovery_action.id} reached the HINGLISH_VOICE handler without "
            "consent_recorded=true — this must never happen; check the policy/state-machine guards"
        )

    script = build_script(
        customer_name=customer.name if customer else None,
        amount=payment.amount,
        currency=payment.currency,
    )
    recipient = (customer.phone if customer else None) or "unknown"
    result = await communication_provider.place_call(script=script, recipient=recipient)
    return {
        "channel": "voice",
        "script": script,
        "connected": result.connected,
        "transcript": result.transcript,
        "provider": result.provider,
        "consent_reconfirmed": result.consent_recorded,
    }
