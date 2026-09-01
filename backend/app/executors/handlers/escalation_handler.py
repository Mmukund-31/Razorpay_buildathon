"""ESCALATION — simulated: no real paging/ops integration in this build. The audit_logs
entry (CASE_ESCALATED) is written by app/services/recovery_case_service.py when the case
transitions to ESCALATED, driven by app/services/execution_service.py firing
CaseTrigger.ESCALATION_COMPLETE after this handler returns — this function's own job is just
to produce the result payload recorded on the `recovery_actions` row.
"""

from app.core.logging import get_logger
from app.domain.models.customer import Customer
from app.domain.models.payment import Payment
from app.domain.models.recovery_action import RecoveryAction

logger = get_logger(__name__)


async def handle(*, recovery_action: RecoveryAction, payment: Payment, customer: Customer | None) -> dict:
    logger.info(
        "case escalated",
        extra={"recovery_action_id": str(recovery_action.id), "payment_id": str(payment.id)},
    )
    return {
        "channel": "internal",
        "reason": "optimizer/policy selected ESCALATION as the highest-expected-value action",
        "amount": payment.amount,
        "currency": payment.currency,
    }
