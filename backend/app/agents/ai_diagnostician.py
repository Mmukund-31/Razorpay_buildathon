"""The AI Diagnostician: the only place an LLM is called in this system, and it is given
ZERO tool/function-calling bindings — it can only return text that this module tries to
parse as `AIDiagnosisOutput` (app/domain/schemas/ai_diagnosis.py). A response that fails
Pydantic validation, or any call that fails outright (no API key, timeout, network error),
is recorded with `is_valid=False` and never reaches the optimizer — see that schema's
docstring and docs/ai-design.md.

Failure handling (docs/reliability.md's "if LLM fails: fallback to deterministic rule engine
or abstain"): a missing API key or any call failure returns an invalid result immediately, no
retries that would slow the pipeline down; a response that isn't valid JSON or fails schema
validation is retried exactly once (LLMs occasionally wrap JSON in prose despite
instructions) before giving up. A simple in-process circuit breaker skips the LLM call
entirely for a cooldown window after too many consecutive failures, so a degraded/unreachable
provider can't add latency to every single case in the meantime.
"""

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.schemas.ai_diagnosis import AIDiagnosisOutput

logger = get_logger(__name__)

_FAILURE_THRESHOLD = 5
_COOLDOWN_SECONDS = 120
_consecutive_failures = 0
_breaker_open_until: float = 0.0


@dataclass(frozen=True, slots=True)
class AIDiagnosisResult:
    is_valid: bool
    output: AIDiagnosisOutput | None
    raw_output: dict
    latency_ms: int
    error: str | None = None


def _breaker_is_open() -> bool:
    return time.monotonic() < _breaker_open_until


def _record_success() -> None:
    global _consecutive_failures
    _consecutive_failures = 0


def _record_failure() -> None:
    global _consecutive_failures, _breaker_open_until
    _consecutive_failures += 1
    if _consecutive_failures >= _FAILURE_THRESHOLD:
        _breaker_open_until = time.monotonic() + _COOLDOWN_SECONDS
        logger.warning(
            "AI diagnostician circuit breaker opened",
            extra={"consecutive_failures": _consecutive_failures, "cooldown_seconds": _COOLDOWN_SECONDS},
        )


def reset_circuit_breaker() -> None:
    """Test hook — clears breaker state between test cases."""
    global _consecutive_failures, _breaker_open_until
    _consecutive_failures, _breaker_open_until = 0, 0.0


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines)
    return stripped.strip()


def _parse(raw_text: str) -> AIDiagnosisOutput:
    cleaned = _strip_markdown_fence(raw_text)
    data = json.loads(cleaned)
    return AIDiagnosisOutput.model_validate(data)


async def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """Isolated so tests can monkeypatch just this function rather than mocking the whole
    Anthropic client chain."""
    settings = get_settings()
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.llm_api_key)
    response = await client.messages.create(
        model=settings.llm_model,
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


async def diagnose(*, system_prompt: str, user_prompt: str) -> AIDiagnosisResult:
    start = time.perf_counter()
    settings = get_settings()

    if not settings.llm_api_key:
        return AIDiagnosisResult(
            is_valid=False,
            output=None,
            raw_output={},
            latency_ms=int((time.perf_counter() - start) * 1000),
            error="no_api_key",
        )

    if _breaker_is_open():
        return AIDiagnosisResult(
            is_valid=False,
            output=None,
            raw_output={},
            latency_ms=int((time.perf_counter() - start) * 1000),
            error="circuit_open",
        )

    last_raw_text = ""
    last_error = ""
    for attempt in range(2):
        try:
            last_raw_text = await _call_llm(system_prompt, user_prompt)
            output = _parse(last_raw_text)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = f"invalid_output:{type(exc).__name__}"
            continue
        except Exception as exc:  # noqa: BLE001 — any API/network failure is "no signal," not a crash
            _record_failure()
            logger.warning("AI diagnostician call failed", extra={"error": str(exc), "attempt": attempt})
            return AIDiagnosisResult(
                is_valid=False,
                output=None,
                raw_output={},
                latency_ms=int((time.perf_counter() - start) * 1000),
                error=f"call_failed:{type(exc).__name__}",
            )
        else:
            _record_success()
            return AIDiagnosisResult(
                is_valid=True,
                output=output,
                raw_output=output.model_dump(mode="json"),
                latency_ms=int((time.perf_counter() - start) * 1000),
            )

    _record_failure()
    return AIDiagnosisResult(
        is_valid=False,
        output=None,
        raw_output={"raw_text": last_raw_text, "parsed_at": datetime.now(UTC).isoformat()},
        latency_ms=int((time.perf_counter() - start) * 1000),
        error=last_error,
    )
