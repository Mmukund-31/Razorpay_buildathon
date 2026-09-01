"""RECOVERYOS_AI baseline + bounded-sample self-documentation

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-01

Widens `ck_experiments_baseline_type` to admit the new `RECOVERYOS_AI` baseline (ML + AI
diagnostician + Optimizer + Policy, run on a bounded evaluation subset — see
simulator/benchmark/baseline_runner.py and docs/ai-ablation.md) alongside the existing 4.
Also adds `experiments.sample_size`/`sampling_seed`, nullable, so a bounded-sample run
records its own sample size and seed at the persistence layer — not only in documentation —
per the "controlled evaluation subset, honestly reported" requirement.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_BASELINE_TYPES = "'ALWAYS_RETRY','STATIC_RULES','ML_ONLY','RECOVERYOS_FULL'"
_NEW_BASELINE_TYPES = "'ALWAYS_RETRY','STATIC_RULES','ML_ONLY','RECOVERYOS_FULL','RECOVERYOS_AI'"


def upgrade() -> None:
    op.drop_constraint("ck_experiments_baseline_type", "experiments", type_="check")
    op.create_check_constraint(
        "ck_experiments_baseline_type", "experiments", f"baseline_type IN ({_NEW_BASELINE_TYPES})"
    )
    op.add_column("experiments", sa.Column("sample_size", sa.Integer(), nullable=True))
    op.add_column("experiments", sa.Column("sampling_seed", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("experiments", "sampling_seed")
    op.drop_column("experiments", "sample_size")
    op.drop_constraint("ck_experiments_baseline_type", "experiments", type_="check")
    op.create_check_constraint(
        "ck_experiments_baseline_type", "experiments", f"baseline_type IN ({_OLD_BASELINE_TYPES})"
    )
