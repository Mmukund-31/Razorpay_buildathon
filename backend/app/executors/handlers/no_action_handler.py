"""NO_ACTION — deliberate no-op. No external call of any kind. Sets
`recovery_actions.status=SKIPPED`, purely for auditability (so "we considered this case and
chose not to act" is as visible in the ledger as any executed action).

REAL in Phase 1 — trivial pure function, no reason to stub it.
"""

from app.domain.enums import RecoveryActionStatus


def handle(*, reason: str) -> dict:
    return {"status": RecoveryActionStatus.SKIPPED.value, "reason": reason}
