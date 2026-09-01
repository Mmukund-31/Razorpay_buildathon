"""payment-link recovery correlation

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-01

Closes the P0 gap where a payment made through a RecoveryOS-created Payment Link (a NEW
`razorpay_payment_id`, distinct from the original failed payment) could never be traced back
to the RecoveryCase that caused the link to exist. See
app/services/outcome_service.py and docs/razorpay-integration.md's payment-link correlation
section for the mechanism this schema supports.

- `recovery_actions.external_reference` gets an index — it's now a lookup key (the created
  Payment Link's id), not just a display field.
- `payments.recovery_action_id` records which RecoveryAction a payment was made *through*,
  once known (nullable — most payments have no recovery history at all).
- `recovery_cases.actual_recovered_amount` is the amount actually captured, written exactly
  once by a conditional UPDATE guarded by `IS NULL` (see
  RecoveryCaseRepository.set_actual_recovered_amount) — distinct from `amount`, which is the
  original at-risk amount, per the product's "never conflate expected and actual recovery"
  rule.
- `recovery_cases.resolved_payment_id` records *which* payment row actually resolved the
  case — this can differ from `recovery_cases.payment_id` (the original failed payment)
  precisely in the payment-link-recovery case this migration exists for.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_recovery_actions_external_reference", "recovery_actions", ["external_reference"]
    )

    op.add_column(
        "payments",
        sa.Column(
            "recovery_action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recovery_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_payments_recovery_action", "payments", ["recovery_action_id"])

    op.add_column("recovery_cases", sa.Column("actual_recovered_amount", sa.BigInteger(), nullable=True))
    op.add_column(
        "recovery_cases",
        sa.Column(
            "resolved_payment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("recovery_cases", "resolved_payment_id")
    op.drop_column("recovery_cases", "actual_recovered_amount")
    op.drop_index("idx_payments_recovery_action", table_name="payments")
    op.drop_column("payments", "recovery_action_id")
    op.drop_index("idx_recovery_actions_external_reference", table_name="recovery_actions")
