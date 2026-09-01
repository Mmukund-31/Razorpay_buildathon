"""Declarative base + the metadata Alembic autogenerates against.

`app.domain.models` imports every model module so `Base.metadata` is complete by the time
`alembic/env.py` reads it — a model that exists but isn't imported here is invisible to
autogenerate and to `Base.metadata.create_all()` in tests.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def register_all_models() -> None:
    """Import every model module for its side effect (registering with Base.metadata).

    Called by alembic/env.py and by tests that need the full schema. Kept as an explicit
    function (rather than relying on import order) so the dependency is obvious.
    """
    from app.domain.models import (  # noqa: F401
        agent_decision,
        audit_log,
        customer,
        experiment,
        experiment_result,
        model_version,
        payment,
        payment_attempt,
        policy_evaluation,
        recovery_action,
        recovery_case,
        recovery_opportunity,
        webhook_event,
    )
