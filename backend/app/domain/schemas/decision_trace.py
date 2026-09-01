"""Response shape for GET /api/recovery-cases/{id}/decision-trace — the full explainability
payload for one case. Populated in Phase 2+; the shape is fixed now so the frontend's
Decision Trace page (Phase 14) and this endpoint can be built independently against the
same contract.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.enums import ActionType, RecoveryCaseStatus
from app.domain.schemas.ai_diagnosis import AIDiagnosisOutput
from app.domain.schemas.policy_decision import PolicyDecision


class PaymentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_id: UUID
    razorpay_payment_id: str
    amount: int
    currency: str
    status: str
    failure_class: str | None
    error_reason: str | None


class CandidateAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: ActionType
    recovery_probability: float
    expected_recovery: float
    intervention_cost: float
    risk_cost: float
    expected_value: float


class ExecutionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: ActionType
    status: str
    channel: str | None
    external_reference: str | None
    executed_at: datetime | None
    result: dict | None = None
    consent_recorded: bool = False


class DecisionTraceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recovery_case_id: UUID
    status: RecoveryCaseStatus
    payment: PaymentContext
    ml_score: float | None
    ai_diagnosis: AIDiagnosisOutput | None
    candidates: list[CandidateAction]
    selected_action: ActionType | None
    policy_decision: PolicyDecision | None
    execution: ExecutionRecord | None
    outcome: str | None
    # EXPECTED recovery (the ML-scored candidate's estimate) vs. ACTUAL recovered revenue
    # (written once, by app/services/outcome_service.py, only once a payment.captured/
    # payment_link.paid signal is reconciled) — deliberately two separate fields so the
    # frontend can never conflate a probability estimate with a verified outcome.
    actual_recovered_amount: int | None
