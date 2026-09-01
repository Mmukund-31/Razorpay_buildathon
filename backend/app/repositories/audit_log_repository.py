"""The Recovery Ledger's only write path. Exposes `add()`/read methods ONLY — deliberately no
`update()`/`delete()` method exists anywhere in this class, which is what makes
audit_logs immutability an application-layer guarantee in Phase 1 (see
app/domain/models/audit_log.py's docstring and tests/unit/test_audit_log_immutability.py).
"""

from app.domain.models.audit_log import AuditLog
from app.repositories.base_repository import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog

    # Intentionally no update()/delete() override or usage — see class docstring.
