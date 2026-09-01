"""Razorpay webhook signature verification — REAL, not a stub.

Verified procedure (docs/razorpay-integration.md): the signature is
`hex(HMAC-SHA256(raw_request_body, webhook_secret))`, sent in the `X-Razorpay-Signature`
header. Verification MUST run against the raw, un-parsed body — parsing first and
re-serializing can change byte-for-byte formatting and silently break every signature.
That's why `app/api/webhooks.py` reads `await request.body()` and passes those exact bytes
here before ever calling `.json()` on the request.
"""

import hashlib
import hmac


def compute_signature(raw_body: bytes, secret: str) -> str:
    """The same HMAC-SHA256 computation `verify_signature` checks against, exposed so the
    simulator (simulator/generators/) can sign the events it generates and send them through
    the real POST /api/webhooks/razorpay verification path — never bypassing it, per ADR-004.
    """
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Constant-time comparison — never use `==` on secrets/signatures (timing side-channel)."""
    if not signature or not secret:
        return False
    return hmac.compare_digest(compute_signature(raw_body, secret), signature)
