"""The PolicyEngine's output contract — see app/policies/policy_engine.py (Phase 7)."""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import PolicyReasonCode


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason_codes: list[PolicyReasonCode] = Field(default_factory=list)
    policy_version: str
    expected_value: float | None = None
