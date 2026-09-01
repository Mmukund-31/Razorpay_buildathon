"""Response shapes for the recovery-cases API surface — kept as Pydantic models (rather than
raw dicts) so FastAPI validates and documents them in the OpenAPI schema automatically.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RecoveryCaseSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    payment_id: UUID
    status: str
    amount: int
    currency: str
    selected_action: str | None
    attempt_count: int
    created_at: datetime
    updated_at: datetime


class RecoveryCaseListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RecoveryCaseSummary]
    total: int
    page: int
    page_size: int


class RecoveryCaseDetail(RecoveryCaseSummary):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID | None
    max_attempts: int
    recovery_window_expires_at: datetime | None
    opportunity_id: UUID
