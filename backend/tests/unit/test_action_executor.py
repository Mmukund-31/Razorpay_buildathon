"""Safety invariant: unknown actions cannot execute. ActionExecutor dispatches strictly on
the 7-value ActionType enum via a dict built at construction — there is no code path that
falls through to executing something unrecognized.
"""

import pytest

from app.domain.enums import ActionType
from app.domain.models.payment import Payment
from app.domain.models.recovery_action import RecoveryAction
from app.executors.action_executor import ActionExecutor, UnknownActionType
from app.executors.handlers.no_action_handler import handle as no_action_handle
from app.integrations.simulator_gateway import SimulatorPaymentLinkAdapter, SimulatorSubscriptionAdapter
from app.services.communication.simulated_voice_provider import SimulatedVoiceProvider
from app.services.communication.text_provider import TextProvider

pytestmark = pytest.mark.unit


class _RoutingProvider:
    def __init__(self):
        self._text = TextProvider()
        self._voice = SimulatedVoiceProvider()

    async def send(self, *, channel, message, recipient):
        return await self._text.send(channel=channel, message=message, recipient=recipient)

    async def place_call(self, *, script, recipient, simulate_response="affirmative"):
        return await self._voice.place_call(
            script=script, recipient=recipient, simulate_response=simulate_response
        )


def _build_executor() -> ActionExecutor:
    return ActionExecutor(
        payment_link_adapter=SimulatorPaymentLinkAdapter(),
        subscription_adapter=SimulatorSubscriptionAdapter(),
        communication_provider=_RoutingProvider(),
    )


def _fake_payment() -> Payment:
    return Payment(razorpay_payment_id="pay_test123", amount=100_00, currency="INR", status="FAILED")


@pytest.mark.asyncio
async def test_unknown_action_type_raises_instead_of_silently_executing():
    executor = _build_executor()
    action = RecoveryAction(action_type="TRANSFER_ALL_FUNDS", idempotency_key="k1", policy_evaluation_id=None)
    with pytest.raises(UnknownActionType):
        await executor.execute(action, _fake_payment(), None)


@pytest.mark.asyncio
async def test_no_action_dispatches_to_the_pure_skip_handler():
    executor = _build_executor()
    action = RecoveryAction(
        action_type=ActionType.NO_ACTION.value, idempotency_key="k2", policy_evaluation_id=None
    )
    result = await executor.execute(action, _fake_payment(), None)
    assert result["status"] == "SKIPPED"


def test_no_action_handler_is_a_pure_noop():
    result = no_action_handle(reason="test")
    assert result == {"status": "SKIPPED", "reason": "test"}


@pytest.mark.asyncio
async def test_smart_retry_dispatches_to_simulator_when_no_real_credentials():
    executor = _build_executor()
    action = RecoveryAction(
        action_type=ActionType.SMART_RETRY.value, idempotency_key="k3", policy_evaluation_id=None
    )
    result = await executor.execute(action, _fake_payment(), None)
    assert result["channel"] == "payment_link"
    assert result["razorpay_payment_link_id"].startswith("sim_plink_")


@pytest.mark.asyncio
async def test_hinglish_voice_refuses_to_dispatch_without_recorded_consent():
    from app.executors.handlers.hinglish_voice_handler import ConsentNotRecorded

    executor = _build_executor()
    action = RecoveryAction(
        action_type=ActionType.HINGLISH_VOICE.value,
        idempotency_key="k4",
        policy_evaluation_id=None,
        consent_recorded=False,
    )
    with pytest.raises(ConsentNotRecorded):
        await executor.execute(action, _fake_payment(), None)
