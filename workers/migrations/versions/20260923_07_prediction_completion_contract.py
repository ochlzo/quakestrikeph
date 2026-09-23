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
        sa.CheckConstraint(
            "probability_m1_plus_24h < 'Infinity'::double precision AND probability_m1_plus_24h > '-Infinity'::double precision AND probability_m4_plus_24h < 'Infinity'::double precision AND probability_m4_plus_24h > '-Infinity'::double precision AND probability_m5_plus_24h < 'Infinity'::double precision AND probability_m5_plus_24h > '-Infinity'::double precision AND expected_m1_plus_count_24h < 'Infinity'::double precision AND expected_m1_plus_count_24h > '-Infinity'::double precision AND (activity_radius_median_km_24h IS NULL OR (activity_radius_median_km_24h < 'Infinity'::double precision AND activity_radius_median_km_24h > '-Infinity'::double precision)) AND (maximum_magnitude_q05_24h IS NULL OR (maximum_magnitude_q05_24h < 'Infinity'::double precision AND maximum_magnitude_q05_24h > '-Infinity'::double precision)) AND (maximum_magnitude_q50_24h IS NULL OR (maximum_magnitude_q50_24h < 'Infinity'::double precision AND maximum_magnitude_q50_24h > '-Infinity'::double precision)) AND (maximum_magnitude_q95_24h IS NULL OR (maximum_magnitude_q95_24h < 'Infinity'::double precision AND maximum_magnitude_q95_24h > '-Infinity'::double precision))",
            name="ck_forecasts_finite_outputs",
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
        sa.CheckConstraint(
            "supersedes_forecast_id IS NULL OR supersedes_forecast_id <> forecast_id",
            name="ck_forecasts_supersedes_other",
        ),
    )
    op.create_index("ix_forecasts_supersedes_forecast_id", "forecasts", ["supersedes_forecast_id"])
    op.execute(
        """
        CREATE FUNCTION enforce_forecast_supersession() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            current_event_id uuid;
            previous_event_id uuid;
        BEGIN
            IF NEW.supersedes_forecast_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT revisions.event_id INTO current_event_id
            FROM prediction_jobs jobs
            JOIN earthquake_event_revisions revisions
              ON revisions.event_revision_id = jobs.event_revision_id
            WHERE jobs.job_id = NEW.job_id;

            SELECT revisions.event_id INTO previous_event_id
            FROM forecasts previous
            JOIN prediction_jobs jobs ON jobs.job_id = previous.job_id
            JOIN earthquake_event_revisions revisions
              ON revisions.event_revision_id = jobs.event_revision_id
            WHERE previous.forecast_id = NEW.supersedes_forecast_id;

            IF previous_event_id IS DISTINCT FROM current_event_id THEN
                RAISE EXCEPTION 'A forecast may supersede only a forecast for the same event.'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_forecasts_supersedes_same_event';
            END IF;

            IF EXISTS (
                WITH RECURSIVE chain(forecast_id, supersedes_forecast_id) AS (
                    SELECT forecast_id, supersedes_forecast_id
                    FROM forecasts
                    WHERE forecast_id = NEW.supersedes_forecast_id
                    UNION
                    SELECT forecasts.forecast_id, forecasts.supersedes_forecast_id
                    FROM forecasts
                    JOIN chain ON forecasts.forecast_id = chain.supersedes_forecast_id
                )
                SELECT 1 FROM chain WHERE forecast_id = NEW.forecast_id
            ) THEN
                RAISE EXCEPTION 'Forecast supersession cannot contain a cycle.'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_forecasts_supersedes_acyclic';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_forecasts_validate_supersession
        BEFORE INSERT OR UPDATE OF forecast_id, job_id, supersedes_forecast_id ON forecasts
        FOR EACH ROW EXECUTE FUNCTION enforce_forecast_supersession()
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_forecast_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Forecasts are immutable.'
                USING ERRCODE = 'check_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_forecasts_immutable
        BEFORE UPDATE ON forecasts
        FOR EACH ROW EXECUTE FUNCTION enforce_forecast_immutable()
        """
    )

    op.create_table(
        "alert_jobs",
        sa.Column("alert_job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("forecast_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("message_snapshot", sa.Text(), nullable=False),
        sa.Column("recipient_policy_snapshot", postgresql.JSONB(), nullable=False),
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
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["forecast_id"], ["forecasts.forecast_id"], onupdate="RESTRICT", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "message_snapshot = btrim(message_snapshot) AND message_snapshot <> ''",
            name="ck_alert_jobs_message",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(recipient_policy_snapshot) = 'object'",
            name="ck_alert_jobs_recipient_policy_object",
        ),
        sa.CheckConstraint("expires_at > requested_at", name="ck_alert_jobs_expiry"),
        sa.CheckConstraint(
            "(status IN ('resolving', 'delivering') AND lease_expires_at IS NOT NULL AND worker_execution_id IS NOT NULL) OR (status NOT IN ('resolving', 'delivering') AND lease_expires_at IS NULL AND worker_execution_id IS NULL)",
            name="ck_alert_jobs_lease",
        ),
        sa.CheckConstraint(
            "(status IN ('completed', 'failed', 'expired') AND completed_at IS NOT NULL) OR (status IN ('pending', 'resolving', 'delivering') AND completed_at IS NULL)",
            name="ck_alert_jobs_completion",
        ),
    )
    op.create_index("ix_alert_jobs_status_expiry", "alert_jobs", ["status", "expires_at"])
    op.create_index("ix_alert_jobs_requested_at", "alert_jobs", ["requested_at"])
    op.create_index(
        "ix_alert_jobs_active_lease",
        "alert_jobs",
        ["lease_expires_at"],
        postgresql_where=sa.text("status IN ('resolving', 'delivering')"),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_alert_snapshots_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.message_snapshot IS DISTINCT FROM OLD.message_snapshot
               OR NEW.recipient_policy_snapshot IS DISTINCT FROM OLD.recipient_policy_snapshot THEN
                RAISE EXCEPTION 'Alert snapshots are immutable.'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_alert_jobs_snapshots_immutable
        BEFORE UPDATE OF message_snapshot, recipient_policy_snapshot ON alert_jobs
        FOR EACH ROW EXECUTE FUNCTION enforce_alert_snapshots_immutable()
        """
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
        sa.CheckConstraint(
            "action = btrim(action) AND action <> '' AND "
            "(actor_service IS NULL OR (actor_service = btrim(actor_service) AND actor_service <> '')) AND "
            "(target_type IS NULL OR (target_type = btrim(target_type) AND target_type <> '')) AND "
            "(target_id IS NULL OR (target_id = btrim(target_id) AND target_id <> '')) AND "
            "(target_revision IS NULL OR (target_revision = btrim(target_revision) AND target_revision <> '')) AND "
            "(reason_code IS NULL OR (reason_code = btrim(reason_code) AND reason_code <> ''))",
            name="ck_audit_logs_identifiers_nonblank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'", name="ck_audit_logs_metadata_object"
        ),
        sa.CheckConstraint("actor_type <> 'user'", name="ck_audit_logs_user_actor_deferred"),
    )
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"])
    op.create_index(
        "ix_audit_logs_actor_occurred_at", "audit_logs", ["actor_user_id", "occurred_at"]
    )
    op.create_index(
        "ix_audit_logs_target_occurred_at",
        "audit_logs",
        ["target_type", "target_id", "occurred_at"],
    )
    op.create_index("ix_audit_logs_correlation_id", "audit_logs", ["correlation_id"])

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
    op.execute("DROP TRIGGER trg_alert_jobs_snapshots_immutable ON alert_jobs")
    op.execute("DROP FUNCTION enforce_alert_snapshots_immutable()")
    op.execute("DROP TRIGGER trg_forecasts_immutable ON forecasts")
    op.execute("DROP FUNCTION enforce_forecast_immutable()")
    for name in (
        "audit_logs",
        "alert_jobs",
        "forecasts",
        "prediction_attempts",
    ):
        op.drop_table(name)
    op.execute("DROP FUNCTION enforce_forecast_supersession()")
    bind = op.get_bind()
    postgresql.ENUM(*ALERT_STATUSES, name="alert_job_status").drop(bind)
    postgresql.ENUM(*ATTEMPT_STATUSES, name="prediction_attempt_status").drop(bind)
