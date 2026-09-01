"""Verifies the Razorpay client and adapters against a mocked HTTP layer (respx) — never a
real network call. No database needed — this suite runs regardless of Postgres availability.
"""

import httpx
import pytest
import respx

from app.core.config import Settings
from app.integrations.payment_link_adapter import PaymentLinkAdapter
from app.integrations.razorpay_client import RAZORPAY_BASE_URL, RazorpayAPIError, RazorpayClient
from app.integrations.subscription_adapter import SubscriptionAdapter

pytestmark = pytest.mark.integration


def test_client_builds_from_settings_with_correct_auth_material():
    settings = Settings(razorpay_key_id="rzp_test_abc123", razorpay_key_secret="shh")
    client = RazorpayClient.from_settings(settings)

    assert client.key_id == "rzp_test_abc123"
    assert client.key_secret == "shh"
    assert client.base_url == RAZORPAY_BASE_URL
    assert client.base_url.startswith("https://")


def test_basic_auth_uses_key_id_and_secret():
    client = RazorpayClient(key_id="my_id", key_secret="my_secret")
    auth = client._auth()

    dummy_request = httpx.Request("GET", f"{RAZORPAY_BASE_URL}/payments")
    prepared = next(auth.auth_flow(dummy_request))
    assert prepared.headers["Authorization"].startswith("Basic ")


@pytest.mark.asyncio
async def test_missing_credentials_refuses_to_call_out():
    client = RazorpayClient(key_id="", key_secret="")
    with pytest.raises(RazorpayAPIError):
        await client._request("POST", "/payment_links")


@pytest.mark.asyncio
@respx.mock
async def test_create_payment_link_shapes_the_real_request_and_response():
    route = respx.post(f"{RAZORPAY_BASE_URL}/payment_links").mock(
        return_value=httpx.Response(
            200, json={"id": "plink_abc123", "short_url": "https://rzp.io/i/xyz", "status": "created"}
        )
    )
    client = RazorpayClient(key_id="rzp_test_id", key_secret="secret")
    adapter = PaymentLinkAdapter(client=client)

    result = await adapter.create_payment_link(
        amount=849900,
        currency="INR",
        reference_id="case-1",
        description="test",
        customer_name="Rahul",
        customer_email=None,
        customer_contact="+919999999999",
        expire_by_seconds=3600,
    )

    assert route.called
    sent_body = route.calls[0].request.content
    assert b'"amount":849900' in sent_body
    assert b'"notify"' in sent_body
    assert result == {
        "razorpay_payment_link_id": "plink_abc123",
        "short_url": "https://rzp.io/i/xyz",
        "status": "created",
    }


@pytest.mark.asyncio
@respx.mock
async def test_retries_on_5xx_then_succeeds():
    route = respx.post(f"{RAZORPAY_BASE_URL}/payment_links").mock(
        side_effect=[
            httpx.Response(503, json={"error": "temporarily unavailable"}),
            httpx.Response(
                200, json={"id": "plink_retry", "short_url": "https://rzp.io/i/r", "status": "created"}
            ),
        ]
    )
    client = RazorpayClient(key_id="id", key_secret="secret")
    adapter = PaymentLinkAdapter(client=client)

    result = await adapter.create_payment_link(
        amount=1000,
        currency="INR",
        reference_id="case-2",
        description="test",
        customer_name=None,
        customer_email=None,
        customer_contact=None,
        expire_by_seconds=3600,
    )

    assert route.call_count == 2
    assert result["razorpay_payment_link_id"] == "plink_retry"


@pytest.mark.asyncio
@respx.mock
async def test_retries_on_429_then_succeeds():
    """429 is Razorpay's rate-limit response — distinct from the generic 5xx case above, and
    specifically listed in RETRYABLE_STATUS_CODES, so it deserves its own test rather than
    riding on the 503 coverage."""
    route = respx.post(f"{RAZORPAY_BASE_URL}/payment_links").mock(
        side_effect=[
            httpx.Response(429, json={"error": {"description": "Too many requests"}}),
            httpx.Response(
                200, json={"id": "plink_429retry", "short_url": "https://rzp.io/i/r429", "status": "created"}
            ),
        ]
    )
    client = RazorpayClient(key_id="id", key_secret="secret")
    adapter = PaymentLinkAdapter(client=client)

    result = await adapter.create_payment_link(
        amount=1000,
        currency="INR",
        reference_id="case-429",
        description="test",
        customer_name=None,
        customer_email=None,
        customer_contact=None,
        expire_by_seconds=3600,
    )

    assert route.call_count == 2
    assert result["razorpay_payment_link_id"] == "plink_429retry"


@pytest.mark.asyncio
@respx.mock
async def test_exhausting_retries_on_429_raises_retryable_error():
    """If Razorpay stays rate-limited for all MAX_RETRIES attempts, the caller must see a
    retryable RazorpayAPIError, not an unhandled exception or a silently-swallowed failure."""
    route = respx.post(f"{RAZORPAY_BASE_URL}/payment_links").mock(
        return_value=httpx.Response(429, json={"error": {"description": "Too many requests"}})
    )
    client = RazorpayClient(key_id="id", key_secret="secret")
    adapter = PaymentLinkAdapter(client=client)

    with pytest.raises(RazorpayAPIError) as exc_info:
        await adapter.create_payment_link(
            amount=1000,
            currency="INR",
            reference_id="case-429-exhausted",
            description="test",
            customer_name=None,
            customer_email=None,
            customer_contact=None,
            expire_by_seconds=3600,
        )

    assert route.call_count == 3  # MAX_RETRIES, no more
    assert exc_info.value.status_code == 429
    assert exc_info.value.retryable


@pytest.mark.asyncio
@respx.mock
async def test_retries_on_timeout_then_succeeds():
    """A network timeout (no HTTP response at all) must be treated the same as a transient
    5xx/429 — retried, not surfaced as an unretryable failure."""
    route = respx.post(f"{RAZORPAY_BASE_URL}/payment_links").mock(
        side_effect=[
            httpx.TimeoutException("timed out"),
            httpx.Response(
                200,
                json={"id": "plink_timeoutretry", "short_url": "https://rzp.io/i/rt", "status": "created"},
            ),
        ]
    )
    client = RazorpayClient(key_id="id", key_secret="secret")
    adapter = PaymentLinkAdapter(client=client)

    result = await adapter.create_payment_link(
        amount=1000,
        currency="INR",
        reference_id="case-timeout",
        description="test",
        customer_name=None,
        customer_email=None,
        customer_contact=None,
        expire_by_seconds=3600,
    )

    assert route.call_count == 2
    assert result["razorpay_payment_link_id"] == "plink_timeoutretry"


@pytest.mark.asyncio
@respx.mock
async def test_exhausting_retries_on_timeout_raises_retryable_error():
    route = respx.post(f"{RAZORPAY_BASE_URL}/payment_links").mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    client = RazorpayClient(key_id="id", key_secret="secret")
    adapter = PaymentLinkAdapter(client=client)

    with pytest.raises(RazorpayAPIError) as exc_info:
        await adapter.create_payment_link(
            amount=1000,
            currency="INR",
            reference_id="case-timeout-exhausted",
            description="test",
            customer_name=None,
            customer_email=None,
            customer_contact=None,
            expire_by_seconds=3600,
        )

    assert route.call_count == 3  # MAX_RETRIES, no more
    assert exc_info.value.retryable


@pytest.mark.asyncio
@respx.mock
async def test_create_payment_link_never_accepts_partial_payment():
    """A recovery Payment Link must always be collected in full — accepting a partial
    settlement would leave the recovery_case in a state nothing downstream reconciles (see
    docs/razorpay-integration.md §4/§10 and app/services/outcome_service.py). This must be
    explicit on every request, not left to Razorpay's own default."""
    route = respx.post(f"{RAZORPAY_BASE_URL}/payment_links").mock(
        return_value=httpx.Response(
            200, json={"id": "plink_partial", "short_url": "https://rzp.io/i/p", "status": "created"}
        )
    )
    client = RazorpayClient(key_id="id", key_secret="secret")
    adapter = PaymentLinkAdapter(client=client)

    await adapter.create_payment_link(
        amount=500000,
        currency="INR",
        reference_id="case-partial",
        description="test",
        customer_name=None,
        customer_email=None,
        customer_contact=None,
        expire_by_seconds=3600,
    )

    sent_body = route.calls[0].request.content
    assert b'"accept_partial":false' in sent_body


@pytest.mark.asyncio
@respx.mock
async def test_does_not_retry_on_4xx():
    route = respx.post(f"{RAZORPAY_BASE_URL}/payment_links").mock(
        return_value=httpx.Response(401, json={"error": {"description": "Authentication failed"}})
    )
    client = RazorpayClient(key_id="bad", key_secret="bad")
    adapter = PaymentLinkAdapter(client=client)

    with pytest.raises(RazorpayAPIError) as exc_info:
        await adapter.create_payment_link(
            amount=1000,
            currency="INR",
            reference_id="case-3",
            description="test",
            customer_name=None,
            customer_email=None,
            customer_contact=None,
            expire_by_seconds=3600,
        )

    assert route.call_count == 1  # no retry on a 4xx
    assert exc_info.value.status_code == 401
    assert not exc_info.value.retryable


@pytest.mark.asyncio
@respx.mock
async def test_subscription_card_change_uses_the_subscription_short_url():
    respx.get(f"{RAZORPAY_BASE_URL}/subscriptions/sub_abc").mock(
        return_value=httpx.Response(200, json={"id": "sub_abc", "short_url": "https://rzp.io/i/sub_abc"})
    )
    client = RazorpayClient(key_id="id", key_secret="secret")
    adapter = SubscriptionAdapter(client=client)

    result = await adapter.request_card_change(razorpay_subscription_id="sub_abc")

    assert result == {"card_change_url": "https://rzp.io/i/sub_abc"}
