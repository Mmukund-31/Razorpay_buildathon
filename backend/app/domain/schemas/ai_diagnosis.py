"""The strict, validated contract the AI Diagnostician's LLM output must satisfy.

This is the entire surface through which the LLM can influence the system — a dict that fails
`AIDiagnosisOutput.model_validate()` never reaches the optimizer at all (see
app/agents/ai_diagnostician.py, Phase 8). `recommended_action` and `communication_mode` are
constrained to the same allowlisted enums the executor dispatches on, so the LLM cannot invent
an action the rest of the system doesn't know how to bound.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ActionType


class AIDiagnosisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_class: str = Field(..., max_length=64)
    diagnosis: str = Field(..., max_length=2000)
    confidence: float = Field(..., ge=0.0, le=1.0)
    recommended_action: ActionType
    reason_codes: list[str] = Field(default_factory=list, max_length=10)
    customer_action_required: bool
    communication_mode: str = Field(..., max_length=32)
