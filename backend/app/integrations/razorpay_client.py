"""Low-level Razorpay REST client — auth, base URL, bounded retry policy. Every
Razorpay-specific HTTP detail lives here and in the two adapters below; no other module is
allowed to import `httpx`/build a Razorpay request directly (see docs/decisions.md ADR-003).

Auth: HTTP Basic with (key_id, key_secret), per Razorpay's documented convention.
Retry: bounded exponential backoff (3 attempts) at THIS layer only, and only for
transient failures (timeouts, 5xx, 429) — a 4xx (bad request, auth failure) is not retried,
since retrying a request Razorpay has already rejected as invalid would just repeat the same
failure. A failure here surfaces as a `RazorpayAPIError`; it is the caller's (executor's) job
to decide what that means for the recovery_action's status, never this client's.
"""

import asyncio
from dataclasses import dataclass

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

RAZORPAY_BASE_URL = "https://api.razorpay.com/v1"
MAX_RETRIES = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
REQUEST_TIMEOUT_SECONDS = 10.0


class RazorpayAPIError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


@dataclass
class RazorpayClient:
    key_id: str
    key_secret: str
    base_url: str = RAZORPAY_BASE_URL

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "RazorpayClient":
        settings = settings or get_settings()
        return cls(key_id=settings.razorpay_key_id, key_secret=settings.razorpay_key_secret)

    def _auth(self) -> httpx.BasicAuth:
        return httpx.BasicAuth(self.key_id, self.key_secret)

    async def _request(self, method: str, path: str, *, json: dict | None = None) -> dict:
        if not self.key_id or not self.key_secret:
            raise RazorpayAPIError("Razorpay credentials not configured", retryable=False)

        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        async with httpx.AsyncClient(auth=self._auth(), timeout=REQUEST_TIMEOUT_SECONDS) as client:
            for attempt in range(MAX_RETRIES):
                try:
                    response = await client.request(method, url, json=json)
                except httpx.TimeoutException as exc:
                    last_error = exc
                    logger.warning(
                        "Razorpay request timed out", extra={"path": path, "attempt": attempt}
                    )
                    await self._backoff(attempt)
                    continue
                except httpx.HTTPError as exc:
                    last_error = exc
                    logger.warning(
                        "Razorpay request failed", extra={"path": path, "error": str(exc), "attempt": attempt}
                    )
                    await self._backoff(attempt)
                    continue

                if response.status_code < 300:
                    return response.json()

                if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES - 1:
                    await self._backoff(attempt)
                    continue

                raise RazorpayAPIError(
                    f"Razorpay returned {response.status_code}: {response.text[:500]}",
                    status_code=response.status_code,
                    retryable=response.status_code in RETRYABLE_STATUS_CODES,
                )

        raise RazorpayAPIError(
            f"Razorpay request failed after {MAX_RETRIES} attempts: {last_error}", retryable=True
        )

    @staticmethod
    async def _backoff(attempt: int) -> None:
        await asyncio.sleep(min(2**attempt * 0.5, 4.0))

    async def get(self, path: str) -> dict:
        return await self._request("GET", path)

    async def post(self, path: str, json: dict) -> dict:
        return await self._request("POST", path, json=json)
