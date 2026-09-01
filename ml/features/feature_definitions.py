"""The feature contract for P(successful recovery | context, candidate_action) — the single
source of truth both ml/training/*.py (Phase 4) and app/agents/ml_predictor.py (Phase 6) build
feature vectors against, so training and inference can never silently drift apart.

Every feature is documented with what it is and, critically, WHY it isn't leakage: nothing
here is derived from information that would only be known after the recovery outcome (e.g.
"was this recovered" or "which action was eventually taken" are excluded on purpose — see
docs/ml-evaluation.md, Phase 18, for the full leakage-prevention discussion).

Both consumers are implemented against exactly this feature list: the synthetic data
generator (ml/data/synthetic_generator.py) and app/agents/ml_predictor.py's feature-vector
builder.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    dtype: str  # "numeric" | "categorical" | "boolean"
    description: str


FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec("amount", "numeric", "Payment amount in paise."),
    FeatureSpec("payment_method", "categorical", "card | upi | netbanking | wallet | emandate."),
    FeatureSpec("failure_class", "categorical", "Derived from Razorpay error.reason, e.g. INSUFFICIENT_FUNDS, AUTH_FAILURE."),
    FeatureSpec("retry_count", "numeric", "Number of prior attempts against this payment."),
    FeatureSpec("time_since_failure_hours", "numeric", "Hours elapsed since the failure event."),
    FeatureSpec("customer_success_rate", "numeric", "Customer's historical successful-payment rate, computed up to (not including) this event."),
    FeatureSpec("customer_failure_rate", "numeric", "Customer's historical failure rate, same cutoff discipline."),
    FeatureSpec("historical_recovery_rate", "numeric", "Customer's historical recovery-after-failure rate."),
    FeatureSpec("customer_lifetime_value", "numeric", "Cumulative captured amount for this customer prior to this event."),
    FeatureSpec("subscription_status", "categorical", "none | active | pending | halted."),
    FeatureSpec("hour_of_day", "numeric", "0-23, local to the merchant's configured timezone."),
    FeatureSpec("day_of_week", "numeric", "0-6."),
    FeatureSpec("previous_response_to_intervention", "categorical", "Outcome of the customer's most recent prior intervention, if any."),
    FeatureSpec("number_of_prior_recoveries", "numeric", "Count of past successful recoveries for this customer."),
    FeatureSpec("candidate_action", "categorical", "The ActionType being scored — P(recovery | context, action)."),
)

FEATURE_NAMES: tuple[str, ...] = tuple(f.name for f in FEATURES)

# Fields that must NEVER appear in FEATURES because they are only known after the outcome —
# guarded by tests/unit/test_feature_engineering.py so a future edit can't reintroduce leakage.
LEAKAGE_EXCLUDED_FIELDS: frozenset[str] = frozenset(
    {"actual_recovered", "recovery_time", "successful_action", "final_attempt_count", "intervention_cost"}
)
