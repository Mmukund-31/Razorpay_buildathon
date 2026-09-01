"""Recovery case endpoints — real, backed by the services wired in Phase 2-11.

`evaluate` and `execute` are idempotent, resumable re-entry points into the same pipeline
`app/services/pipeline_orchestrator.py` drives autonomously from a webhook: calling either on
a case that's already past the relevant stage is a safe no-op (the case is simply returned as
it stands), not a duplicate action — see the idempotency guarantees in
app/services/execution_service.py and app/domain/recovery_case_state_machine.py.
"""

import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.errors import AppError
from app.domain.enums import RecoveryCaseStatus
from app.domain.models.payment import Payment
from app.domain.models.recovery_case import RecoveryCase
from app.domain.recovery_case_state_machine import CaseTrigger
from app.domain.schemas.decision_trace import DecisionTraceResponse
from app.domain.schemas.recovery_case_responses import (
    RecoveryCaseDetail,
    RecoveryCaseListResponse,
    RecoveryCaseSummary,
)
from app.repositories.recovery_case_repository import RecoveryCaseRepository
from app.services import analysis_service, decision_trace_service, execution_service, policy_service
from app.services import recovery_case_service as case_service

router = APIRouter()


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent_recorded: bool = False


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent_recorded: bool = False


def _to_summary(case: RecoveryCase) -> RecoveryCaseSummary:
    return RecoveryCaseSummary(
        id=case.id,
        payment_id=case.payment_id,
        status=case.status,
        amount=case.amount,
        currency=case.currency,
        selected_action=case.selected_action,
        attempt_count=case.attempt_count,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


async def _get_case_or_404(db: DbSession, case_id: uuid.UUID) -> RecoveryCase:
    case = await RecoveryCaseRepository(db).get(case_id)
    if case is None:
        raise AppError(
            code="RECOVERY_CASE_NOT_FOUND",
            message=f"No recovery case with id {case_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return case


@router.get("/recovery-cases", response_model=RecoveryCaseListResponse)
async def list_recovery_cases(
    db: DbSession, status_filter: str | None = None, page: int = 1, page_size: int = 25
) -> RecoveryCaseListResponse:
    items, total = await RecoveryCaseRepository(db).list_filtered(
        status=status_filter, page=page, page_size=page_size
    )
    return RecoveryCaseListResponse(
        items=[_to_summary(c) for c in items], total=total, page=page, page_size=page_size
    )


@router.get("/recovery-cases/{case_id}", response_model=RecoveryCaseDetail)
async def get_recovery_case(case_id: uuid.UUID, db: DbSession) -> RecoveryCaseDetail:
    case = await _get_case_or_404(db, case_id)
    return RecoveryCaseDetail(
        **_to_summary(case).model_dump(),
        customer_id=case.customer_id,
        max_attempts=case.max_attempts,
        recovery_window_expires_at=case.recovery_window_expires_at,
        opportunity_id=case.opportunity_id,
    )


@router.get("/recovery-cases/{case_id}/decision-trace", response_model=DecisionTraceResponse)
async def get_decision_trace(case_id: uuid.UUID, db: DbSession) -> DecisionTraceResponse:
    case = await _get_case_or_404(db, case_id)
    payment = (await db.execute(select(Payment).where(Payment.id == case.payment_id))).scalar_one_or_none()
    if payment is None:
        raise AppError(
            code="PAYMENT_NOT_FOUND",
            message=f"Recovery case {case_id} references a missing payment.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    trace = await decision_trace_service.build(db, case, payment)
    await db.commit()
    return trace


@router.post("/recovery-cases/{case_id}/evaluate", response_model=RecoveryCaseDetail)
async def evaluate_recovery_case(
    case_id: uuid.UUID, db: DbSession, body: EvaluateRequest
) -> RecoveryCaseDetail:
    case = await _get_case_or_404(db, case_id)
    correlation_id = uuid.uuid4()

    if case.status == RecoveryCaseStatus.ELIGIBLE.value:
        case = await case_service.transition(db, case, CaseTrigger.START_ANALYSIS, correlation_id)
    if case.status == RecoveryCaseStatus.ANALYZING.value:
        case = await analysis_service.analyze(db, case, correlation_id)
    if case.status == RecoveryCaseStatus.ACTION_PROPOSED.value:
        case = await policy_service.evaluate_and_transition(
            db, case, correlation_id, consent_recorded=body.consent_recorded
        )

    await db.commit()
    return await get_recovery_case(case.id, db)


@router.post("/recovery-cases/{case_id}/execute", response_model=RecoveryCaseDetail)
async def execute_recovery_case(
    case_id: uuid.UUID, db: DbSession, body: ExecuteRequest
) -> RecoveryCaseDetail:
    case = await _get_case_or_404(db, case_id)

    if case.status not in (RecoveryCaseStatus.POLICY_APPROVED.value, RecoveryCaseStatus.SCHEDULED.value):
        raise AppError(
            code="CASE_NOT_READY_FOR_EXECUTION",
            message=f"Case {case_id} is in status {case.status}, not POLICY_APPROVED/SCHEDULED.",
            status_code=status.HTTP_409_CONFLICT,
        )

    correlation_id = uuid.uuid4()
    case = await execution_service.execute(db, case, correlation_id, consent_recorded=body.consent_recorded)
    await db.commit()
    return await get_recovery_case(case.id, db)
