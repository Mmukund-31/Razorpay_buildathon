"""Sends simulator-generated webhook payloads through the REAL
`POST /api/webhooks/razorpay` endpoint — signature computed and verified exactly like a real
Razorpay delivery would be — via an in-process ASGI call, so the exact same route handler,
signature check, idempotent-insert, and background-worker pipeline run as for real traffic
(ADR-004: never a parallel fake path).

`app.main` is imported lazily inside each function, not at module level — `app.api.simulator`
(which calls into this module) is itself imported by `app.api.router`, which `app.main`
imports, so a top-level `from app.main import app` here would be a circular import at
process-startup time. Deferred imports don't have that problem.
"""

import json
import uuid

from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.integrations.webhook_verifier import compute_signature


async def post_event(payload: dict, *, event_id: str | None = None) -> dict:
    """Signs and posts one webhook payload through the real endpoint. Returns the endpoint's
    JSON response ({"status": "ok", "duplicate": bool} on success)."""
    from app.main import app  # deferred import — avoids a circular import, see module docstring

    settings = get_settings()
    body = json.dumps(payload).encode("utf-8")
    signature = compute_signature(body, settings.razorpay_webhook_secret)
    headers = {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": event_id or f"evt_sim_{uuid.uuid4().hex}",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://simulator") as client:
        response = await client.post("/api/webhooks/razorpay", content=body, headers=headers)
    return {"status_code": response.status_code, "body": response.json()}


async def post_events(payloads: list[dict]) -> list[dict]:
    return [await post_event(p) for p in payloads]
