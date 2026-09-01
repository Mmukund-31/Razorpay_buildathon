"""The deterministic Policy Gate — the ONLY thing that can move a recovery_case to
POLICY_APPROVED. `evaluate()` always returns a `PolicyDecision`, never raises for a normal
reject, so the caller can always persist a policy_evaluations row, allowed or not.

Runs every rule in `app.policies.rules.ALL_RULES` in order and collects EVERY reason code
that fired (not just the first) — a candidate that fails 3 rules should show all 3 in the
decision trace, not just whichever happened to be checked first.
"""

from app.domain.schemas.policy_decision import PolicyDecision
from app.policies.rules import ALL_RULES, PolicyContext

POLICY_VERSION = "policy-v1"


class PolicyEngine:
    def __init__(self, policy_version: str = POLICY_VERSION) -> None:
        self.policy_version = policy_version

    def evaluate(self, context: PolicyContext) -> PolicyDecision:
        reason_codes = [code for rule in ALL_RULES if (code := rule(context)) is not None]
        return PolicyDecision(
            allowed=not reason_codes,
            reason_codes=reason_codes,
            policy_version=self.policy_version,
            expected_value=context.expected_value,
        )
