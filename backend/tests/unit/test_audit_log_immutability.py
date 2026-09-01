"""Application-layer enforcement of the Recovery Ledger's immutability: neither
AuditLogRepository nor the BaseRepository it builds on exposes any update/delete method — see
app/domain/models/audit_log.py's docstring. A future edit that adds one would be caught here,
not discovered later as a silent ledger-tampering bug.
"""

import inspect

import pytest

from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.base_repository import BaseRepository

pytestmark = pytest.mark.unit

FORBIDDEN_METHOD_NAMES = {"update", "delete", "remove", "modify", "patch"}


def _public_method_names(cls: type) -> set[str]:
    return {
        name
        for name, _ in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def test_audit_log_repository_exposes_no_mutating_methods():
    assert not (_public_method_names(AuditLogRepository) & FORBIDDEN_METHOD_NAMES)


def test_base_repository_itself_exposes_no_mutating_methods():
    assert not (_public_method_names(BaseRepository) & FORBIDDEN_METHOD_NAMES)
