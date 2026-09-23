"""Add prediction completion, automatic alert, and audit persistence."""

# ruff: noqa: E501

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260923_07"
down_revision = "20260918_06"
branch_labels = None
depends_on = None

ATTEMPT_STATUSES = ("running", "succeeded", "failed", "abandoned")
ALERT_STATUSES = (
    "pending",
    "resolving",
    "delivering",
    "completed",
    "failed",
    "cancelled",
    "expired",
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*ATTEMPT_STATUSES, name="prediction_attempt_status").create(bind)
    postgresql.ENUM(*ALERT_STATUSES, name="alert_job_status").create(bind)

    op.create_table(
        "prediction_attempts",
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*ATTEMPT_STATUSES, name="prediction_attempt_status", create_type=False),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("worker_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.ForeignKeyConstraint(
            ["job_id"], ["prediction_jobs.job_id"], onupdate="RESTRICT", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_prediction_attempts_job_number"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_prediction_attempts_number"),
        sa.CheckConstraint(
            "(status = 'running' AND lease_expires_at IS NOT NULL AND finished_at IS NULL) OR (status <> 'running' AND lease_expires_at IS NULL AND finished_at IS NOT NULL)",
            name="ck_prediction_attempts_state",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_prediction_attempts_finish_order",
        ),
        sa.CheckConstraint(
            "(error_code IS NULL OR (error_code = btrim(error_code) AND error_code <> '')) AND (error_message IS NULL OR (error_message = btrim(error_message) AND error_message <> ''))",
            name="ck_prediction_attempts_errors_nonblank",
        ),
    )
    op.create_index(
        "uq_prediction_attempts_one_running",
        "prediction_attempts",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_prediction_attempts_running_lease",
        "prediction_attempts",
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "forecasts",
        sa.Column("forecast_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("supersedes_forecast_id", postgresql.UUID(as_uuid=True)),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("probability_m1_plus_24h", sa.Double(), nullable=False),
        sa.Column("expected_m1_plus_count_24h", sa.Double(), nullable=False),
        sa.Column("probability_m4_plus_24h", sa.Double(), nullable=False),
        sa.Column("probability_m5_plus_24h", sa.Double(), nullable=False),
        sa.Column("activity_radius_median_km_24h", sa.Double()),
        sa.Column("maximum_magnitude_q05_24h", sa.Double()),
        sa.Column("maximum_magnitude_q50_24h", sa.Double()),
        sa.Column("maximum_magnitude_q95_24h", sa.Double()),
        sa.Column("additional_output_json", postgresql.JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["prediction_jobs.job_id"], onupdate="RESTRICT", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_forecast_id"],
            ["forecasts.forecast_id"],
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "window_end = window_start + interval '24 hours'", name="ck_forecasts_24h_window"
        ),
        sa.CheckConstraint(
            "probability_m1_plus_24h BETWEEN 0 AND 1 AND probability_m4_plus_24h BETWEEN 0 AND 1 AND probability_m5_plus_24h BETWEEN 0 AND 1 AND probability_m5_plus_24h <= probability_m4_plus_24h AND probability_m4_plus_24h <= probability_m1_plus_24h",
            name="ck_forecasts_probabilities",
        ),
        sa.CheckConstraint("expected_m1_plus_count_24h >= 0", name="ck_forecasts_expected_count"),
        sa.CheckConstraint(
            "activity_radius_median_km_24h IS NULL OR activity_radius_median_km_24h >= 0",
            name="ck_forecasts_radius",
        ),
        sa.CheckConstraint(
            "(maximum_magnitude_q05_24h IS NULL AND maximum_magnitude_q50_24h IS NULL AND maximum_magnitude_q95_24h IS NULL) OR (maximum_magnitude_q05_24h IS NOT NULL AND maximum_magnitude_q50_24h IS NOT NULL AND maximum_magnitude_q95_24h IS NOT NULL AND maximum_magnitude_q05_24h <= maximum_magnitude_q50_24h AND maximum_magnitude_q50_24h <= maximum_magnitude_q95_24h)",
            name="ck_forecasts_quantiles",
        ),
    )
    op.create_index("ix_forecasts_supersedes_forecast_id", "forecasts", ["supersedes_forecast_id"])

    op.create_table(
        "alert_jobs",
        sa.Column("alert_job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("forecast_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_id", postgresql.UUID(as_uuid=True)),
        sa.Column("alert_type", sa.Text(), nullable=False),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("requested_by_service", sa.Text()),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("channel", sa.Text(), nullable=False, server_default="sms"),
        sa.Column("message_snapshot", sa.Text(), nullable=False),
        sa.Column("recipient_policy_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "status",
            postgresql.ENUM(*ALERT_STATUSES, name="alert_job_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("recipient_resolution_completed_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("worker_execution_id", postgresql.UUID(as_uuid=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancellation_reason", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["forecast_id"], ["forecasts.forecast_id"], onupdate="RESTRICT", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "alert_type IN ('operator_review', 'automatic_model')", name="ck_alert_jobs_type"
        ),
        sa.CheckConstraint("channel = 'sms'", name="ck_alert_jobs_channel"),
        sa.CheckConstraint(
            "message_snapshot = btrim(message_snapshot) AND message_snapshot <> ''",
            name="ck_alert_jobs_message",
        ),
        sa.CheckConstraint(
            "idempotency_key = btrim(idempotency_key) AND idempotency_key <> ''",
            name="ck_alert_jobs_idempotency",
        ),
        sa.CheckConstraint("expires_at > requested_at", name="ck_alert_jobs_expiry"),
        sa.CheckConstraint(
            "(alert_type = 'automatic_model' AND requested_by_service = btrim(requested_by_service) AND requested_by_service <> '' AND requested_by_user_id IS NULL AND review_id IS NULL) OR (alert_type = 'operator_review' AND requested_by_user_id IS NOT NULL AND requested_by_service IS NULL AND review_id IS NOT NULL)",
            name="ck_alert_jobs_requester",
        ),
        sa.CheckConstraint(
            "(status IN ('resolving', 'delivering') AND lease_expires_at IS NOT NULL AND worker_execution_id IS NOT NULL) OR (status NOT IN ('resolving', 'delivering') AND lease_expires_at IS NULL AND worker_execution_id IS NULL)",
            name="ck_alert_jobs_lease",
        ),
        sa.CheckConstraint(
            "(status IN ('completed', 'failed', 'cancelled', 'expired') AND completed_at IS NOT NULL) OR (status IN ('pending', 'resolving', 'delivering') AND completed_at IS NULL)",
            name="ck_alert_jobs_completion",
        ),
        sa.CheckConstraint(
            "(status = 'cancelled' AND cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL) OR (status <> 'cancelled' AND cancelled_at IS NULL AND cancellation_reason IS NULL)",
            name="ck_alert_jobs_cancellation",
        ),
    )
    op.create_index(
        "uq_alert_jobs_automatic_forecast_channel",
        "alert_jobs",
        ["forecast_id", "channel"],
        unique=True,
        postgresql_where=sa.text("alert_type = 'automatic_model'"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("actor_service", sa.Text()),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text()),
        sa.Column("target_id", sa.Text()),
        sa.Column("target_revision", sa.Text()),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text()),
        sa.Column("request_id", postgresql.UUID(as_uuid=True)),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB()),
        sa.CheckConstraint(
            "actor_type IN ('user', 'system', 'anonymous')", name="ck_audit_logs_actor_type"
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'denied', 'failed')", name="ck_audit_logs_outcome"
        ),
        sa.CheckConstraint(
            "(actor_type = 'user' AND actor_user_id IS NOT NULL AND actor_service IS NULL) OR (actor_type = 'system' AND actor_user_id IS NULL AND actor_service IS NOT NULL) OR (actor_type = 'anonymous' AND actor_user_id IS NULL AND actor_service IS NULL)",
            name="ck_audit_logs_actor_identity",
        ),
        sa.CheckConstraint(
            "(target_type IS NULL AND target_id IS NULL) OR (target_type IS NOT NULL AND target_id IS NOT NULL)",
            name="ck_audit_logs_target_pair",
        ),
    )

    op.drop_constraint("ck_job_dispatches_alert_target_deferred", "job_dispatches", type_="check")
    op.create_foreign_key(
        "fk_job_dispatches_alert_job",
        "job_dispatches",
        "alert_jobs",
        ["alert_job_id"],
        ["alert_job_id"],
        onupdate="RESTRICT",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_job_dispatches_alert_job", "job_dispatches", type_="foreignkey")
    op.create_check_constraint(
        "ck_job_dispatches_alert_target_deferred", "job_dispatches", "alert_job_id IS NULL"
    )
    for name in ("audit_logs", "alert_jobs", "forecasts", "prediction_attempts"):
        op.drop_table(name)
    bind = op.get_bind()
    postgresql.ENUM(*ALERT_STATUSES, name="alert_job_status").drop(bind)
    postgresql.ENUM(*ATTEMPT_STATUSES, name="prediction_attempt_status").drop(bind)
