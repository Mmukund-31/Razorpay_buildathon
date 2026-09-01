"""Real aggregate queries backing GET /api/dashboard — the Command Center. Every number here
is computed from live rows, never hand-authored (docs/decisions.md's "no fabricated
metrics" rule applies to the dashboard just as much as the benchmark).
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import RECOVERY_CASE_LIVE_STATUSES, RecoveryCaseStatus
from app.domain.models.recovery_action import RecoveryAction
from app.domain.models.recovery_case import RecoveryCase
from app.domain.models.recovery_opportunity import RecoveryOpportunity


async def get_dashboard_metrics(session: AsyncSession) -> dict:
    live_statuses = [s.value for s in RECOVERY_CASE_LIVE_STATUSES]

    amount_at_risk = (
        await session.execute(
            select(func.coalesce(func.sum(RecoveryOpportunity.amount_at_risk), 0)).where(
                RecoveryOpportunity.status == "OPEN"
            )
        )
    ).scalar_one()

    recoverable = (
        await session.execute(
            select(func.coalesce(func.sum(RecoveryCase.amount), 0)).where(
                RecoveryCase.status.in_(live_statuses)
            )
        )
    ).scalar_one()

    # ACTUAL recovered revenue, not the case's original at-risk amount — the two can differ
    # (a partially-paid recovery Payment Link, or simply because "recovered" and "the amount
    # we originally flagged as at risk" are two different facts). See
    # app/services/outcome_service.py, which is the only writer of this column.
    recovered = (
        await session.execute(
            select(func.coalesce(func.sum(RecoveryCase.actual_recovered_amount), 0)).where(
                RecoveryCase.status == RecoveryCaseStatus.SUCCEEDED.value
            )
        )
    ).scalar_one()

    total_cases, succeeded_cases = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(RecoveryCase.status == RecoveryCaseStatus.SUCCEEDED.value),
            ).select_from(RecoveryCase)
        )
    ).one()
    recovery_rate = (succeeded_cases / total_cases) if total_cases else 0.0

    active_cases = (
        await session.execute(
            select(func.count()).select_from(RecoveryCase).where(RecoveryCase.status.in_(live_statuses))
        )
    ).scalar_one()

    actions_executed = (
        await session.execute(
            select(func.count()).select_from(RecoveryAction).where(RecoveryAction.status == "SUCCEEDED")
        )
    ).scalar_one()

    actions_prevented = (
        await session.execute(
            select(func.count())
            .select_from(RecoveryCase)
            .where(RecoveryCase.status == RecoveryCaseStatus.POLICY_REJECTED.value)
        )
    ).scalar_one()

    abstentions = (
        await session.execute(
            select(func.count())
            .select_from(RecoveryCase)
            .where(RecoveryCase.status == RecoveryCaseStatus.ABSTAINED.value)
        )
    ).scalar_one()

    recent = (
        await session.execute(select(RecoveryCase).order_by(RecoveryCase.created_at.desc()).limit(10))
    ).scalars()

    return {
        "total_amount_at_risk": int(amount_at_risk),
        "total_recoverable": int(recoverable),
        "total_recovered": int(recovered or 0),
        "recovery_rate": round(recovery_rate, 4),
        "active_cases_count": int(active_cases),
        "actions_executed_count": int(actions_executed),
        "actions_prevented_count": int(actions_prevented),
        "abstentions_count": int(abstentions),
        "recent_cases": [
            {
                "id": str(c.id),
                "payment_id": str(c.payment_id),
                "status": c.status,
                "amount": c.amount,
                "currency": c.currency,
                "selected_action": c.selected_action,
            }
            for c in recent
        ],
    }
