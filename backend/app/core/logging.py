"""Structured JSON logging.

Every log line is a JSON object so `request_id` / `correlation_id` / `payment_id` /
`recovery_case_id` / `action_id` fields (attached via `extra=`) are queryable, not buried in a
free-text message. Never log secrets — request/webhook bodies are logged as hashes or field
lists in the audit ledger, never raw, and API keys/webhook secrets are never logged at all.
"""

import logging
import sys

from pythonjsonlogger import json as jsonlogger

from app.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
