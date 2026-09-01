"""Ties every pipeline stage together for one webhook event, end to end:

  state reconstruction -> revenue signal -> opportunity -> case -> eligibility -> analysis
  (ML+AI+optimizer) -> policy -> execution

This is what app/core/background_worker.py's real per-event handler calls. It is also what a
later payment.captured webhook uses to resolve a still-open case for the same payment — see
`_resolve_if_captured` below, which is the concrete wiring behind
`CaseTrigger.PAYMENT_CAPTURED_EXTERNALLY` (app/domain/recovery_case_state_machine.py).

Every stage is independently callable (via the API's evaluate/execute endpoints) — this
orchestrator is a convenience that chains them for the fully-autonomous path, not the only
way to reach them.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.enums import PaymentStatus, RecoveryCaseStatus
from app.domain.models.payment import Payment
from app.domain.models.webhook_event import WebhookEvent
from app.domain.recovery_case_state_machine import CaseTrigger
from app.policies.rules import CONSENT_REQUIRED_ACTIONS
from app.repositories.recovery_case_repository import RecoveryCaseRepository
from app.services import (
    analysis_service,
    execution_service,
    policy_service,
    recovery_case_service,
    revenue_signal_service,
    state_reconstruction_service,
)

logger = get_logger(__name__)


async def handle_webhook_event(session: AsyncSession, webhook_event: WebhookEvent) -> None:
    correlation_id = uuid.uuid4()
    payment = await state_reconstruction_service.apply(session, webhook_event, correlation_id)
    if payment is None:
        return  # not a payment-carrying event (e.g. subscription.*, downtime.*) — out of scope

    if payment.status == PaymentStatus.CAPTURED.value:
        await _resolve_if_captured(session, payment, correlation_id)
        return

    if payment.status == PaymentStatus.FAILED.value:
        await process_failed_payment(session, payment, correlation_id)


async def _resolve_if_captured(session: AsyncSession, payment: Payment, correlation_id: uuid.UUID) -> None:
    case_repo = RecoveryCaseRepository(session)
    live_case = await case_repo.get_live_case_for_payment(payment.id)
    if live_case is None:
        return
    await recovery_case_service.transition(
        session, live_case, CaseTrigger.PAYMENT_CAPTURED_EXTERNALLY, correlation_id
    )


async def process_failed_payment(session: AsyncSession, payment: Payment, correlation_id: uuid.UUID):
    """Drives a FAILED payment all the way from opportunity detection through execution.
    Returns the resulting RecoveryCase, or None if the payment wasn't eligible at all (e.g.
    below the revenue-at-risk floor, or an opportunity already existed)."""
    opportunity = await revenue_signal_service.detect_opportunity(session, payment, correlation_id)
    if opportunity is None:
        return None

    case = await recovery_case_service.create_case_from_opportunity(session, opportunity, correlation_id)
    case = await recovery_case_service.evaluate_eligibility(session, case, correlation_id)
    if case.status != RecoveryCaseStatus.ELIGIBLE.value:
        return case

    case = await recovery_case_service.transition(session, case, CaseTrigger.START_ANALYSIS, correlation_id)
    if case.status != RecoveryCaseStatus.ANALYZING.value:
        return case

    case = await analysis_service.analyze(session, case, correlation_id)
    if case.status != RecoveryCaseStatus.ACTION_PROPOSED.value:
        return case

    if case.selected_action in {a.value for a in CONSENT_REQUIRED_ACTIONS}:
        # The autonomous pipeline has no live customer interaction to capture consent from —
        # rather than auto-rejecting via the policy gate (which would terminally close the
        # case in POLICY_REJECTED, unrecoverable even once consent is later granted), it
        # deliberately stops here. The case sits in ACTION_PROPOSED — genuinely "awaiting
        # consent" — until a human/simulated consent step calls POST .../evaluate with
        # consent_recorded=true, which resumes exactly this policy-evaluation step. See
        # docs/demo-script.md's Hinglish voice section.
        logger.info(
            "case awaiting consent before policy evaluation",
            extra={"case_id": str(case.id), "action": case.selected_action},
        )
        return case

    case = await policy_service.evaluate_and_transition(session, case, correlation_id)
    if case.status != RecoveryCaseStatus.POLICY_APPROVED.value:
        return case

    return await execution_service.execute(session, case, correlation_id)
