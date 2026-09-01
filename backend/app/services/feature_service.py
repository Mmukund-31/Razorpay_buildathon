"""Builds the feature vector `ml/features/feature_definitions.py` contracts, from live
database state, for one payment/case/customer. Every historical-rate feature is computed
from events strictly BEFORE the current payment's failure — the same cutoff discipline the
synthetic generator follows (see ml/data/synthetic_generator.py) — so training and inference
apply leakage prevention the same way.

Does not include `candidate_action` — that's added per-action by app/agents/ml_predictor.py
when scoring a specific candidate.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import PaymentStatus
from app.domain.models.payment import Payment
from app.domain.models.recovery_action import RecoveryAction
from app.domain.models.recovery_case import RecoveryCase


async def build_features(session: AsyncSession, payment: Payment, case: RecoveryCase) -> dict:
    now = datetime.now(UTC)
    customer_stats = await _customer_stats(session, payment.customer_id, before=payment.created_at)
    previous_response = await _previous_response(session, payment.customer_id, before=payment.created_at)

    return {
        "amount": payment.amount,
        "payment_method": payment.method or "unknown",
        "failure_class": payment.failure_class or "OTHER",
        "retry_count": case.attempt_count,
        "time_since_failure_hours": max(
            0.0, (now - (payment.last_event_created_at or now)).total_seconds() / 3600
        ),
        "customer_success_rate": customer_stats["success_rate"],
        "customer_failure_rate": customer_stats["failure_rate"],
        "historical_recovery_rate": customer_stats["recovery_rate"],
        "customer_lifetime_value": customer_stats["lifetime_value"],
        "subscription_status": "none",
        "hour_of_day": now.hour,
        "day_of_week": now.weekday(),
        "previous_response_to_intervention": previous_response,
        "number_of_prior_recoveries": customer_stats["prior_recoveries"],
    }


async def _customer_stats(session: AsyncSession, customer_id, *, before: datetime) -> dict:
    if customer_id is None:
        return {
            "success_rate": 0.5,
            "failure_rate": 0.5,
            "recovery_rate": 0.3,
            "lifetime_value": 0.0,
            "prior_recoveries": 0,
        }

    totals = (
        await session.execute(
            select(
                func.count().filter(Payment.status == PaymentStatus.CAPTURED.value),
                func.count().filter(Payment.status == PaymentStatus.FAILED.value),
                func.coalesce(
                    func.sum(Payment.amount).filter(Payment.status == PaymentStatus.CAPTURED.value), 0
                ),
            ).where(Payment.customer_id == customer_id, Payment.created_at < before)
        )
    ).one()
    captured_count, failed_count, lifetime_value = totals
    total_events = captured_count + failed_count
    success_rate = captured_count / total_events if total_events else 0.5
    failure_rate = failed_count / total_events if total_events else 0.5

    recovered_cases = (
        await session.execute(
            select(func.count())
            .select_from(RecoveryCase)
            .where(
                RecoveryCase.customer_id == customer_id,
                RecoveryCase.status == "SUCCEEDED",
                RecoveryCase.created_at < before,
            )
        )
    ).scalar_one()
    recovery_rate = recovered_cases / failed_count if failed_count else 0.3

    return {
        "success_rate": round(success_rate, 4),
        "failure_rate": round(failure_rate, 4),
        "recovery_rate": round(min(recovery_rate, 1.0), 4),
        "lifetime_value": float(lifetime_value or 0),
        "prior_recoveries": int(recovered_cases),
    }


async def _previous_response(session: AsyncSession, customer_id, *, before: datetime) -> str:
    if customer_id is None:
        return "none"
    last_action = (
        await session.execute(
            select(RecoveryAction.channel)
            .join(RecoveryCase, RecoveryAction.recovery_case_id == RecoveryCase.id)
            .where(RecoveryCase.customer_id == customer_id, RecoveryAction.created_at < before)
            .order_by(RecoveryAction.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return last_action or "none"
