"""Synthetic recovery-outcome dataset generator (product spec §16-17).

Design, not just noise: every row is one (payment-failure context, candidate_action) pair
with a ground-truth outcome sampled from a probability function that encodes the
relationships the spec requires, not independently-random columns:

  * INSUFFICIENT_FUNDS: low immediate-retry probability, higher for actions that give the
    customer time/agency (DELAYED_RETRY, CUSTOMER_ACTION_REQUEST).
  * AUTH_FAILURE: low probability for any pure retry (SMART_RETRY/DELAYED_RETRY) since the
    problem isn't timing — CUSTOMER_ACTION_REQUEST (fix your card/OTP) scores meaningfully
    higher.
  * GATEWAY_TIMEOUT / NETWORK_ERROR: transient — SMART_RETRY/DELAYED_RETRY score highest.
  * RISK_BLOCKED: low across the board; nothing but ESCALATION is realistic.
  * repeated failures (`retry_count`) multiplicatively decay every action's probability.
  * `historical_recovery_rate` (the customer's own track record, computed with a strict
    time-ordered cutoff — never including the row's own outcome) is blended in as a strong
    predictor, satisfying "historical recovery: strong predictive signal."
  * HINGLISH_VOICE gets an extra boost when `previous_response_to_intervention == "voice"`,
    modeling the "voice > SMS for this customer" pattern the product spec's example scenario
    describes.
  * higher `customer_lifetime_value` customers get a small positive nudge (proxy for more
    reliable payment relationships), satisfying "high-value customers: higher economic
    opportunity" without conflating value and recoverability more than that.

No column is independently random: outcomes and every derived ground-truth column
(`actual_recovered`, `recovery_time`, `successful_action`, `attempt_count`,
`intervention_cost`) follow directly from this shared probability model, seeded
deterministically for reproducibility.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `import ml.*`

from ml.features.feature_definitions import FEATURE_NAMES  # noqa: E402

DATASET_VERSION = "synthetic-v1"

ACTIONS = (
    "SMART_RETRY",
    "DELAYED_RETRY",
    "CUSTOMER_NOTIFICATION",
    "CUSTOMER_ACTION_REQUEST",
    "HINGLISH_VOICE",
    "ESCALATION",
    "NO_ACTION",
)

FAILURE_CLASSES = (
    "INSUFFICIENT_FUNDS",
    "AUTH_FAILURE",
    "GATEWAY_TIMEOUT",
    "BANK_DECLINE",
    "NETWORK_ERROR",
    "RISK_BLOCKED",
    "OTHER",
)
FAILURE_CLASS_WEIGHTS = (0.30, 0.18, 0.12, 0.20, 0.08, 0.05, 0.07)

PAYMENT_METHODS = ("upi", "card", "netbanking", "wallet", "emandate")
PAYMENT_METHOD_WEIGHTS = (0.45, 0.30, 0.12, 0.08, 0.05)

# Base P(recovery | failure_class, action) — the "true" relationship the model must learn.
# Deliberately hand-authored per the spec's required qualitative relationships, not fit to
# anything (there is nothing to fit to — this function IS the ground truth).
_BASE_PROBABILITY: dict[str, dict[str, float]] = {
    "INSUFFICIENT_FUNDS": {
        "SMART_RETRY": 0.14, "DELAYED_RETRY": 0.42, "CUSTOMER_NOTIFICATION": 0.20,
        "CUSTOMER_ACTION_REQUEST": 0.46, "HINGLISH_VOICE": 0.38, "ESCALATION": 0.10, "NO_ACTION": 0.09,
    },
    "AUTH_FAILURE": {
        "SMART_RETRY": 0.08, "DELAYED_RETRY": 0.11, "CUSTOMER_NOTIFICATION": 0.18,
        "CUSTOMER_ACTION_REQUEST": 0.33, "HINGLISH_VOICE": 0.27, "ESCALATION": 0.09, "NO_ACTION": 0.05,
    },
    "GATEWAY_TIMEOUT": {
        "SMART_RETRY": 0.62, "DELAYED_RETRY": 0.58, "CUSTOMER_NOTIFICATION": 0.30,
        "CUSTOMER_ACTION_REQUEST": 0.35, "HINGLISH_VOICE": 0.40, "ESCALATION": 0.12, "NO_ACTION": 0.22,
    },
    "BANK_DECLINE": {
        "SMART_RETRY": 0.20, "DELAYED_RETRY": 0.28, "CUSTOMER_NOTIFICATION": 0.19,
        "CUSTOMER_ACTION_REQUEST": 0.34, "HINGLISH_VOICE": 0.31, "ESCALATION": 0.11, "NO_ACTION": 0.10,
    },
    "NETWORK_ERROR": {
        "SMART_RETRY": 0.58, "DELAYED_RETRY": 0.55, "CUSTOMER_NOTIFICATION": 0.28,
        "CUSTOMER_ACTION_REQUEST": 0.30, "HINGLISH_VOICE": 0.34, "ESCALATION": 0.10, "NO_ACTION": 0.20,
    },
    "RISK_BLOCKED": {
        "SMART_RETRY": 0.04, "DELAYED_RETRY": 0.05, "CUSTOMER_NOTIFICATION": 0.06,
        "CUSTOMER_ACTION_REQUEST": 0.09, "HINGLISH_VOICE": 0.08, "ESCALATION": 0.15, "NO_ACTION": 0.02,
    },
    "OTHER": {
        "SMART_RETRY": 0.24, "DELAYED_RETRY": 0.26, "CUSTOMER_NOTIFICATION": 0.20,
        "CUSTOMER_ACTION_REQUEST": 0.28, "HINGLISH_VOICE": 0.25, "ESCALATION": 0.10, "NO_ACTION": 0.12,
    },
}

# Recovery-time distribution per action, in hours (used only when the row is recovered).
_RECOVERY_TIME_HOURS: dict[str, tuple[float, float]] = {  # (lognormal mean, sigma) of log-hours
    "SMART_RETRY": (0.2, 0.6),
    "DELAYED_RETRY": (3.4, 0.5),
    "CUSTOMER_NOTIFICATION": (2.0, 0.8),
    "CUSTOMER_ACTION_REQUEST": (2.6, 0.7),
    "HINGLISH_VOICE": (-1.2, 0.7),
    "ESCALATION": (3.0, 0.9),
    "NO_ACTION": (2.8, 1.0),
}

# Placeholder cost model, paise — mirrors backend/app/core/config.py's defaults for
# consistency between the dataset and the live optimizer (see docs/decisions.md ADR-006).
_INTERVENTION_COST_PAISE: dict[str, int] = {
    "SMART_RETRY": 20, "DELAYED_RETRY": 20, "CUSTOMER_NOTIFICATION": 20,
    "CUSTOMER_ACTION_REQUEST": 20, "HINGLISH_VOICE": 500, "ESCALATION": 0, "NO_ACTION": 0,
}

_PREVIOUS_RESPONSES = ("none", "sms", "voice", "email")
_PREVIOUS_RESPONSE_WEIGHTS = (0.55, 0.20, 0.15, 0.10)


@dataclass
class SyntheticCustomer:
    id: int
    true_recovery_propensity: float
    value_tier: str
    lifetime_value_base: float
    success_count: int = 0
    failure_count: int = 0
    recovery_count: int = 0
    prior_recoveries: int = 0
    last_response: str = "none"


def _make_customers(rng: np.random.Generator, n_customers: int) -> list[SyntheticCustomer]:
    tiers = rng.choice(["low", "mid", "high"], size=n_customers, p=[0.60, 0.30, 0.10])
    propensities = rng.beta(2.2, 3.0, size=n_customers)
    tier_multiplier = {"low": 1.0, "mid": 3.5, "high": 12.0}
    customers = []
    for i in range(n_customers):
        base_ltv = float(rng.lognormal(mean=8.5, sigma=0.7)) * tier_multiplier[tiers[i]]
        customers.append(
            SyntheticCustomer(
                id=i,
                true_recovery_propensity=float(propensities[i]),
                value_tier=str(tiers[i]),
                lifetime_value_base=base_ltv,
            )
        )
    return customers


def _clip01(x: float) -> float:
    return max(0.01, min(0.99, x))


def true_recovery_probability(
    *,
    failure_class: str,
    action: str,
    retry_count: int,
    historical_recovery_rate: float,
    has_history: bool,
    value_tier: str,
    true_recovery_propensity: float,
    last_response: str,
    time_since_failure_hours: float,
) -> float:
    """The ground-truth P(recovery | context, action) this synthetic world was built from —
    extracted out of `generate()`'s per-row loop so it can also answer counterfactual
    queries ("what if action X had been chosen instead") for
    simulator/benchmark/baseline_runner.py. This is legitimate here (and only here) because
    the synthetic world's true probability function is, by construction, exactly known —
    real logged data would need off-policy correction to ask the same question honestly.
    """
    base_p = _BASE_PROBABILITY[failure_class][action]
    retry_decay = 0.72**retry_count
    history_blend = 0.65 * base_p + 0.35 * (historical_recovery_rate if has_history else base_p)
    propensity_blend = 0.8 * history_blend + 0.2 * true_recovery_propensity

    value_bonus = 0.0
    if value_tier == "high":
        value_bonus = 0.03
    elif value_tier == "mid":
        value_bonus = 0.015

    voice_bonus = 0.15 if (action == "HINGLISH_VOICE" and last_response == "voice") else 0.0
    recency_penalty = 0.08 if (action == "SMART_RETRY" and time_since_failure_hours > 24) else 0.0

    return _clip01(propensity_blend * retry_decay + value_bonus + voice_bonus - recency_penalty)


def generate(n_rows: int = 50_000, seed: int = 42) -> pd.DataFrame:
    """Deterministic for a given (n_rows, seed). Returns a DataFrame with every column in
    FEATURE_NAMES plus the ground-truth columns (actual_recovered, recovery_time,
    successful_action, attempt_count, intervention_cost) and `dataset_version`.
    """
    rng = np.random.default_rng(seed)
    n_customers = max(1, n_rows // 3)
    customers = _make_customers(rng, n_customers)

    customer_idx = rng.integers(0, n_customers, size=n_rows)
    failure_classes = rng.choice(FAILURE_CLASSES, size=n_rows, p=FAILURE_CLASS_WEIGHTS)
    methods = rng.choice(PAYMENT_METHODS, size=n_rows, p=PAYMENT_METHOD_WEIGHTS)
    actions = rng.choice(ACTIONS, size=n_rows)
    retry_counts = rng.poisson(0.6, size=n_rows).clip(0, 5)
    time_since_failure = rng.exponential(8.0, size=n_rows).clip(0.05, 168)
    hours = rng.integers(0, 24, size=n_rows)
    days = rng.integers(0, 7, size=n_rows)
    amounts = (rng.lognormal(mean=7.2, sigma=1.0, size=n_rows) * 100).astype(int).clip(500, 5_000_000)
    prev_responses = rng.choice(_PREVIOUS_RESPONSES, size=n_rows, p=_PREVIOUS_RESPONSE_WEIGHTS)
    subscription_status = rng.choice(
        ["none", "active", "pending", "halted"], size=n_rows, p=[0.55, 0.25, 0.12, 0.08]
    )

    rows: list[dict] = []
    # Process in the row order generated above; each customer's running stats are updated
    # AFTER their features are read for the current row — this is the leakage-prevention
    # "cutoff discipline" feature_definitions.py's docstring requires.
    for i in range(n_rows):
        cust = customers[customer_idx[i]]
        action = str(actions[i])
        failure_class = str(failure_classes[i])
        retry_count = int(retry_counts[i])

        total_events = cust.success_count + cust.failure_count
        customer_success_rate = cust.success_count / total_events if total_events else 0.5
        customer_failure_rate = cust.failure_count / total_events if total_events else 0.5
        historical_recovery_rate = (
            cust.recovery_count / cust.failure_count if cust.failure_count else 0.3
        )

        final_p = true_recovery_probability(
            failure_class=failure_class,
            action=action,
            retry_count=retry_count,
            historical_recovery_rate=historical_recovery_rate,
            has_history=bool(cust.failure_count),
            value_tier=cust.value_tier,
            true_recovery_propensity=cust.true_recovery_propensity,
            last_response=cust.last_response,
            time_since_failure_hours=float(time_since_failure[i]),
        )
        recovered = bool(rng.random() < final_p)

        recovery_time = None
        if recovered:
            mu, sigma = _RECOVERY_TIME_HOURS[action]
            recovery_time = round(float(rng.lognormal(mean=mu, sigma=sigma)), 2)

        rows.append(
            {
                "amount": int(amounts[i]),
                "payment_method": str(methods[i]),
                "failure_class": failure_class,
                "retry_count": retry_count,
                "time_since_failure_hours": round(float(time_since_failure[i]), 2),
                "customer_success_rate": round(customer_success_rate, 4),
                "customer_failure_rate": round(customer_failure_rate, 4),
                "historical_recovery_rate": round(historical_recovery_rate, 4),
                "customer_lifetime_value": round(cust.lifetime_value_base, 2),
                "subscription_status": str(subscription_status[i]),
                "hour_of_day": int(hours[i]),
                "day_of_week": int(days[i]),
                "previous_response_to_intervention": str(prev_responses[i]),
                "number_of_prior_recoveries": cust.prior_recoveries,
                "candidate_action": action,
                "actual_recovered": recovered,
                "recovery_time": recovery_time,
                "successful_action": action if recovered else None,
                "attempt_count": retry_count,
                "intervention_cost": _INTERVENTION_COST_PAISE[action],
                "customer_id": cust.id,
                "dataset_version": DATASET_VERSION,
            }
        )

        cust.failure_count += 1
        if recovered:
            cust.recovery_count += 1
            cust.success_count += 1
            cust.prior_recoveries += 1
        cust.last_response = str(prev_responses[i]) if action != "NO_ACTION" else cust.last_response

    df = pd.DataFrame(rows)
    missing = set(FEATURE_NAMES) - set(df.columns)
    assert not missing, f"generator is missing contracted features: {missing}"
    return df


def split(df: pd.DataFrame, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """70/15/15 train/validation/test, shuffled with the same seed for reproducibility.
    Split by row, not by customer — acceptable here since the ML task is
    P(recovery | context, action) for a given event, not a per-customer forecast; documented
    as a known limitation in docs/ml-evaluation.md.
    """
    shuffled = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    n = len(shuffled)
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)
    return shuffled.iloc[:train_end], shuffled.iloc[train_end:val_end], shuffled.iloc[val_end:]
