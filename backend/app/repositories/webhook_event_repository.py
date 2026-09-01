"""Webhook event persistence. The idempotent-insert-catches-IntegrityError pattern is already
implemented inline in app/api/webhooks.py for Phase 1; this repository is where that logic
moves once the ingestion service (Phase 2) owns it instead of the route handler directly.
"""

from app.domain.models.webhook_event import WebhookEvent
from app.repositories.base_repository import BaseRepository


class WebhookEventRepository(BaseRepository[WebhookEvent]):
    model = WebhookEvent
