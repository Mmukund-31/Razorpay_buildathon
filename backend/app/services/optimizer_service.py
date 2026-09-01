"""The Intervention Optimizer's expected-value math — REAL, not a stub, because it's pure and
self-contained (no I/O), which is exactly what makes it independently unit-testable.

expected_recovery = probability_of_recovery * payment_amount
expected_value     = expected_recovery - intervention_cost - risk_cost

Candidate generation itself (which actions are considered, where their probability/cost
estimates come from) lives in app/services/analysis_service.py — this module only owns the
arithmetic and the placeholder cost model, kept together because the cost model is what
`compute_expected_value` is parameterized by.
"""

from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.domain.enums import ActionType


def compute_expected_recovery(probability_of_recovery: float, amount: int) -> float:
    if not 0.0 <= probability_of_recovery <= 1.0:
        raise ValueError("probability_of_recovery must be in [0, 1]")
    return probability_of_recovery * amount


def compute_expected_value(
    probability_of_recovery: float,
    amount: int,
    *,
    intervention_cost: float = 0.0,
    risk_cost: float = 0.0,
) -> float:
    expected_recovery = compute_expected_recovery(probability_of_recovery, amount)
    return expected_recovery - intervention_cost - risk_cost


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    action_type: ActionType
    probability_of_recovery: float
    expected_recovery: float
    intervention_cost: float
    risk_cost: float
    expected_value: float


def rank_candidates(candidates: list[ScoredCandidate]) -> list[ScoredCandidate]:
    """argmax(expected_value), full ranking returned so the policy gate and decision trace
    can show what else was considered and why it lost."""
    return sorted(candidates, key=lambda c: c.expected_value, reverse=True)


def intervention_cost_paise(action: ActionType, settings: Settings | None = None) -> int:
    """Placeholder cost model (docs/decisions.md ADR-006) — every action costs at least the
    default SMS/payment-link-delivery cost; HINGLISH_VOICE costs meaningfully more, modeling
    a real (simulated) telephony cost. Not fit to any data — a documented starting point."""
    settings = settings or get_settings()
    if action == ActionType.HINGLISH_VOICE:
        return settings.hinglish_voice_intervention_cost_paise
    if action in (ActionType.ESCALATION, ActionType.NO_ACTION):
        return 0
    return settings.default_intervention_cost_paise


def risk_cost_paise(action: ActionType, settings: Settings | None = None) -> int:
    """Proxies the intangible cost of annoying/alienating a customer — highest for the most
    intrusive channel (a phone call), non-zero for any customer-facing message, zero for
    actions that don't reach the customer at all."""
    settings = settings or get_settings()
    if action == ActionType.HINGLISH_VOICE:
        return settings.hinglish_voice_risk_cost_paise
    if action in (ActionType.CUSTOMER_NOTIFICATION, ActionType.CUSTOMER_ACTION_REQUEST):
        return settings.notification_risk_cost_paise
    return 0
