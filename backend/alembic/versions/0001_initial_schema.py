"""initial schema — 13 tables per docs/architecture.md domain model

Revision ID: 0001
Revises:
Create Date: 2026-08-28

Creates all 13 tables in FK-safe order, every CHECK constraint mirroring
app/domain/enums.py, the partial unique index enforcing "at most one live recovery_case per
payment", and the unique index preventing duplicate recovery_opportunities. No native
Postgres ENUM types, no pgcrypto/uuid-ossp extensions (see docs/decisions.md ADR-001).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- customers ---
    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("razorpay_contact_id", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("opted_out", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("opted_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opted_out_channel", sa.String(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("idx_customers_phone", "customers", ["phone"])
    op.create_index("idx_customers_email", "customers", ["email"])
    op.create_index(
        "uq_customers_razorpay_contact_id",
        "customers",
        ["razorpay_contact_id"],
        unique=True,
        postgresql_where=sa.text("razorpay_contact_id IS NOT NULL"),
    )

    # --- payments ---
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("razorpay_payment_id", sa.String(), nullable=False, unique=True),
        sa.Column("razorpay_order_id", sa.String(), nullable=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(), nullable=False, server_default="CREATED"),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_description", sa.String(), nullable=True),
        sa.Column("error_source", sa.String(), nullable=True),
        sa.Column("error_step", sa.String(), nullable=True),
        sa.Column("error_reason", sa.String(), nullable=True),
        sa.Column("failure_class", sa.String(), nullable=True),
        sa.Column("last_event_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_sequence_id", sa.BigInteger(), nullable=True),
        sa.Column("is_terminal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_entity", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('CREATED','AUTHORIZED','CAPTURED','FAILED','REFUNDED','UNKNOWN')",
            name="ck_payments_status",
        ),
    )
    op.create_index("idx_payments_customer", "payments", ["customer_id"])
    op.create_index("idx_payments_status", "payments", ["status"])
    op.create_index("idx_payments_order", "payments", ["razorpay_order_id"])

    # --- payment_attempts ---
    op.create_table(
        "payment_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("razorpay_order_id", sa.String(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_description", sa.String(), nullable=True),
        sa.Column("error_source", sa.String(), nullable=True),
        sa.Column("error_step", sa.String(), nullable=True),
        sa.Column("error_reason", sa.String(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("payment_id", "attempt_number", name="uq_payment_attempts_payment_attempt"),
    )
    op.create_index("idx_payment_attempts_payment", "payment_attempts", ["payment_id"])

    # --- webhook_events ---
    op.create_table(
        "webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("razorpay_event_id", sa.String(), nullable=False, unique=True),
        sa.Column("sequence_id", sa.BigInteger(), sa.Identity(always=False), nullable=False, unique=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("signature_valid", sa.Boolean(), nullable=False),
        sa.Column("raw_body", sa.LargeBinary(), nullable=False),
        sa.Column("headers", postgresql.JSONB(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("razorpay_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processing_status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("processing_error", sa.String(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "processing_status IN ('PENDING','PROCESSING','PROCESSED','FAILED','IGNORED_STALE')",
            name="ck_webhook_events_processing_status",
        ),
    )
    op.create_index("idx_webhook_events_status_seq", "webhook_events", ["processing_status", "sequence_id"])

    # --- model_versions ---
    op.create_table(
        "model_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("model_type", sa.String(), nullable=False),
        sa.Column("training_dataset_ref", sa.String(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=True),
        sa.Column("artifact_path", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", "version", name="uq_model_versions_name_version"),
    )

    # --- recovery_opportunities ---
    op.create_table(
        "recovery_opportunities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("opportunity_type", sa.String(), nullable=False),
        sa.Column("amount_at_risk", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("webhook_events.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="OPEN"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "opportunity_type IN ('ONE_TIME_PAYMENT_FAILURE','SUBSCRIPTION_PENDING','SUBSCRIPTION_HALTED')",
            name="ck_recovery_opportunities_type",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','CONVERTED_TO_CASE','DISMISSED')",
            name="ck_recovery_opportunities_status",
        ),
        sa.UniqueConstraint("payment_id", "opportunity_type", name="uq_recovery_opportunities_payment_type"),
    )

    # --- recovery_cases ---
    op.create_table(
        "recovery_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "opportunity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recovery_opportunities.id"),
            nullable=False,
        ),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="DETECTED"),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("recovery_window_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("selected_action", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DETECTED','ELIGIBLE','ANALYZING','ACTION_PROPOSED','POLICY_REJECTED',"
            "'POLICY_APPROVED','SCHEDULED','EXECUTING','SUCCEEDED','FAILED','ESCALATED',"
            "'ABSTAINED','EXPIRED')",
            name="ck_recovery_cases_status",
        ),
        sa.UniqueConstraint("opportunity_id", name="uq_recovery_cases_opportunity"),
    )
    op.create_index("idx_recovery_cases_status", "recovery_cases", ["status"])
    op.create_index("idx_recovery_cases_payment", "recovery_cases", ["payment_id"])
    op.create_index(
        "uq_recovery_cases_one_live_per_payment",
        "recovery_cases",
        ["payment_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('FAILED','EXPIRED','ABSTAINED')"),
    )

    # --- policy_evaluations ---
    op.create_table(
        "policy_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "recovery_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recovery_cases.id"),
            nullable=False,
        ),
        sa.Column("candidate_action", sa.String(), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("expected_value", sa.Numeric(), nullable=True),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_policy_evaluations_case", "policy_evaluations", ["recovery_case_id"])

    # --- recovery_actions ---
    op.create_table(
        "recovery_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "recovery_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recovery_cases.id"),
            nullable=False,
        ),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
        sa.Column("external_reference", sa.String(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("consent_recorded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("consent_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "policy_evaluation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("policy_evaluations.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action_type IN ('SMART_RETRY','DELAYED_RETRY','CUSTOMER_NOTIFICATION',"
            "'CUSTOMER_ACTION_REQUEST','HINGLISH_VOICE','ESCALATION','NO_ACTION')",
            name="ck_recovery_actions_action_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','EXECUTING','SUCCEEDED','FAILED','SKIPPED')",
            name="ck_recovery_actions_status",
        ),
    )
    op.create_index("idx_recovery_actions_case", "recovery_actions", ["recovery_case_id"])

    # --- agent_decisions ---
    op.create_table(
        "agent_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "recovery_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recovery_cases.id"),
            nullable=False,
        ),
        sa.Column("decision_type", sa.String(), nullable=False),
        sa.Column(
            "model_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_versions.id"),
            nullable=True,
        ),
        sa.Column("input_features", postgresql.JSONB(), nullable=True),
        sa.Column("raw_output", postgresql.JSONB(), nullable=False),
        sa.Column("validated_output", postgresql.JSONB(), nullable=True),
        sa.Column("is_valid", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "decision_type IN ('ML_PREDICTION','AI_DIAGNOSIS')",
            name="ck_agent_decisions_decision_type",
        ),
    )
    op.create_index("idx_agent_decisions_case", "agent_decisions", ["recovery_case_id"])

    # --- audit_logs (append-only ledger — see docs/security.md) ---
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("model_version", sa.String(), nullable=True),
        sa.Column("policy_version", sa.String(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("idx_audit_logs_correlation", "audit_logs", ["correlation_id"])

    # --- experiments ---
    op.create_table(
        "experiments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("baseline_type", sa.String(), nullable=False),
        sa.Column("dataset_ref", sa.String(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "baseline_type IN ('ALWAYS_RETRY','STATIC_RULES','ML_ONLY','RECOVERYOS_FULL')",
            name="ck_experiments_baseline_type",
        ),
    )

    # --- experiment_results ---
    op.create_table(
        "experiment_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "experiment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("experiments.id"), nullable=False
        ),
        sa.Column("metric_name", sa.String(), nullable=False),
        sa.Column("metric_value", sa.Numeric(), nullable=False),
        sa.Column("segment", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "experiment_id", "metric_name", "segment", name="uq_experiment_results_metric_segment"
        ),
    )


def downgrade() -> None:
    op.drop_table("experiment_results")
    op.drop_table("experiments")
    op.drop_table("audit_logs")
    op.drop_table("agent_decisions")
    op.drop_table("recovery_actions")
    op.drop_table("policy_evaluations")
    op.drop_table("recovery_cases")
    op.drop_table("recovery_opportunities")
    op.drop_table("model_versions")
    op.drop_table("webhook_events")
    op.drop_table("payment_attempts")
    op.drop_table("payments")
    op.drop_table("customers")
