"""Generates a batch of realistic, correlated (not independently random — mirrors
ml/data/synthetic_generator.py's distributions, see docs/ml-evaluation.md) synthetic
payment-failure events, as full Razorpay-shaped webhook payloads ready to POST through
`POST /api/webhooks/razorpay`. Backs the same endpoint.
"""

import numpy as np

from simulator.generators.event_generator import build_payment_failed_event, new_simulated_payment

DEFAULT_FAILURE_DISTRIBUTION = {
    "INSUFFICIENT_FUNDS": 0.30,
    "AUTH_FAILURE": 0.18,
    "GATEWAY_TIMEOUT": 0.12,
    "BANK_DECLINE": 0.20,
    "NETWORK_ERROR": 0.08,
    "RISK_BLOCKED": 0.05,
    "OTHER": 0.07,
}

_ERROR_REASON_BY_CLASS = {
    "INSUFFICIENT_FUNDS": ("insufficient_funds", "Insufficient balance in account"),
    "AUTH_FAILURE": ("payment_authentication_failed", "Authentication failed"),
    "GATEWAY_TIMEOUT": ("gateway_timeout", "Gateway timed out"),
    "BANK_DECLINE": ("issuer_declined", "Card declined by issuing bank"),
    "NETWORK_ERROR": ("network_error", "Network error occurred"),
    "RISK_BLOCKED": ("risk_blocked", "Blocked by risk checks"),
    "OTHER": ("payment_failed", "Payment failed"),
}


def generate_failure_storm(
    *,
    count: int,
    failure_distribution: dict[str, float] | None = None,
    amount_distribution: tuple[float, float] = (7.2, 1.0),  # (lognormal mean, sigma) of log-paise
    seed: int = 42,
) -> list[dict]:
    """Returns a list of ready-to-POST Razorpay-shaped webhook payloads."""
    distribution = failure_distribution or DEFAULT_FAILURE_DISTRIBUTION
    classes = list(distribution.keys())
    weights = np.array(list(distribution.values()), dtype=float)
    weights = weights / weights.sum()

    rng = np.random.default_rng(seed)
    chosen_classes = rng.choice(classes, size=count, p=weights)
    amounts = (rng.lognormal(*amount_distribution, size=count) * 100).astype(int).clip(500, 5_000_000)
    methods = rng.choice(["upi", "card", "netbanking", "wallet"], size=count, p=[0.5, 0.3, 0.12, 0.08])

    events = []
    for i in range(count):
        failure_class = str(chosen_classes[i])
        error_reason, error_description = _ERROR_REASON_BY_CLASS[failure_class]
        payment = new_simulated_payment(amount=int(amounts[i]), method=str(methods[i]))
        events.append(
            build_payment_failed_event(
                payment=payment,
                error_reason=error_reason,
                error_description=error_description,
            )
        )
    return events
