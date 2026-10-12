"""Create the six-table ingestion foundation."""

# ruff: noqa: E501

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_01"
down_revision = None
branch_labels = None
depends_on = None

RUN_STATUSES = ("pending", "running", "retry_wait", "succeeded", "failed", "cancelled")
JOB_STATUSES = RUN_STATUSES
DISPATCH_STATUSES = ("pending", "dispatching", "enqueued", "retry_wait", "stopped")


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*RUN_STATUSES, name="ingestion_run_status").create(bind)
    postgresql.ENUM(*JOB_STATUSES, name="prediction_job_status").create(bind)
    postgresql.ENUM(*DISPATCH_STATUSES, name="dispatch_status").create(bind)

    op.create_table(
        "ingestion_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trigger_type", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*RUN_STATUSES, name="ingestion_run_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("worker_execution_id", postgresql.UUID(as_uuid=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("events_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("events_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("events_revised", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("events_unchanged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("events_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "trigger_type IN ('scheduled', 'manual', 'backfill')",
            name="ck_ingestion_runs_trigger_type",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_ingestion_runs_attempt_count_nonnegative"
        ),
        sa.CheckConstraint(
            "events_found >= 0 AND events_inserted >= 0 AND events_revised >= 0 AND events_unchanged >= 0 AND events_rejected >= 0",
            name="ck_ingestion_runs_counters_nonnegative",
        ),
        sa.CheckConstraint(
            "(error_code IS NULL OR (error_code = btrim(error_code) AND error_code <> '')) AND (error_message IS NULL OR (error_message = btrim(error_message) AND error_message <> ''))",
            name="ck_ingestion_runs_errors_nonblank",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND started_at IS NOT NULL AND lease_expires_at IS NOT NULL AND worker_execution_id IS NOT NULL AND finished_at IS NULL) OR (status <> 'running' AND lease_expires_at IS NULL AND worker_execution_id IS NULL)",
            name="ck_ingestion_runs_running_lease",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded', 'failed', 'cancelled') AND finished_at IS NOT NULL) OR (status IN ('pending', 'running', 'retry_wait') AND finished_at IS NULL)",
            name="ck_ingestion_runs_finished_state",
        ),
        sa.CheckConstraint(
            "status <> 'pending' OR started_at IS NULL",
            name="ck_ingestion_runs_pending_not_started",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="ck_ingestion_runs_finish_order",
        ),
    )
    op.create_index(
        "uq_ingestion_runs_one_active",
        "ingestion_runs",
        [sa.text("(status IS NOT NULL)")],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running', 'retry_wait')"),
    )
    op.create_index(
        "ix_ingestion_runs_running_lease",
        "ingestion_runs",
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "earthquake_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("first_seen_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_seen_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("superseded_by_event_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["first_seen_run_id"],
            ["ingestion_runs.run_id"],
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_run_id"],
            ["ingestion_runs.run_id"],
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_event_id"],
            ["earthquake_events.event_id"],
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "superseded_by_event_id IS NULL OR superseded_by_event_id <> event_id",
            name="ck_earthquake_events_no_self_supersession",
        ),
    )
    op.create_index(
        "ix_earthquake_events_first_seen_run_id", "earthquake_events", ["first_seen_run_id"]
    )
    op.create_index(
        "ix_earthquake_events_last_seen_run_id", "earthquake_events", ["last_seen_run_id"]
    )
    op.create_index(
        "ix_earthquake_events_superseded_by_event_id",
        "earthquake_events",
        ["superseded_by_event_id"],
    )

    op.create_table(
        "earthquake_event_revisions",
        sa.Column("event_revision_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_bulletin_id", sa.Text()),
        sa.Column("source_event_group_id", sa.Text()),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_time_precision", sa.Text(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 6), nullable=False),
        sa.Column("depth_km", sa.Numeric(10, 3), nullable=False),
        sa.Column("magnitude", sa.Numeric(5, 2), nullable=False),
        sa.Column("location_description", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text()),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["earthquake_events.event_id"], onupdate="RESTRICT", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.run_id"],
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "event_id", "revision_number", name="uq_event_revisions_event_revision"
        ),
        sa.CheckConstraint("revision_number >= 1", name="ck_event_revisions_revision_number"),
        sa.CheckConstraint(
            "source_bulletin_id IS NOT NULL OR source_event_group_id IS NOT NULL",
            name="ck_event_revisions_source_identifier",
        ),
        sa.CheckConstraint(
            "source_bulletin_id IS NULL OR (source_bulletin_id = btrim(source_bulletin_id) AND source_bulletin_id <> '' AND source_bulletin_id = upper(source_bulletin_id))",
            name="ck_event_revisions_bulletin_id",
        ),
        sa.CheckConstraint(
            "source_event_group_id IS NULL OR (source_event_group_id = btrim(source_event_group_id) AND source_event_group_id <> '' AND source_event_group_id = upper(source_event_group_id))",
            name="ck_event_revisions_group_id",
        ),
        sa.CheckConstraint(
            "source_url = btrim(source_url) AND source_url <> ''",
            name="ck_event_revisions_source_url_nonblank",
        ),
        sa.CheckConstraint(
            "source_time_precision IN ('minute', 'second')",
            name="ck_event_revisions_time_precision",
        ),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_event_revisions_latitude"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_event_revisions_longitude"),
        sa.CheckConstraint("depth_km >= 0", name="ck_event_revisions_depth"),
        sa.CheckConstraint(
            "latitude NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND longitude NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND depth_km NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND magnitude NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="ck_event_revisions_observations_finite",
        ),
        sa.CheckConstraint(
            "location_description = btrim(location_description) AND location_description <> ''",
            name="ck_event_revisions_location_nonblank",
        ),
        sa.CheckConstraint(
            "origin IS NULL OR origin IN ('TECTONIC', 'VOLCANIC', 'TECTONIC-VOLCANIC')",
            name="ck_event_revisions_origin",
        ),
    )
    op.create_index(
        "uq_event_revisions_source_bulletin_id",
        "earthquake_event_revisions",
        ["source_bulletin_id"],
        unique=True,
        postgresql_where=sa.text("source_bulletin_id IS NOT NULL"),
    )
    op.create_index(
        "ix_event_revisions_source_event_group_id",
        "earthquake_event_revisions",
        ["source_event_group_id"],
    )
    op.create_index(
        "ix_event_revisions_ingestion_run_id", "earthquake_event_revisions", ["ingestion_run_id"]
    )

    op.create_table(
        "model_releases",
        sa.Column("model_release_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version_label", sa.Text(), nullable=False, unique=True),
        sa.Column("artifact_manifest_uri", sa.Text(), nullable=False),
        sa.Column("artifact_manifest_hash", sa.Text(), nullable=False),
        sa.Column("input_schema_version", sa.Text(), nullable=False),
        sa.Column("output_schema_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "version_label = btrim(version_label) AND version_label <> ''",
            name="ck_model_releases_version_label_nonblank",
        ),
        sa.CheckConstraint(
            "artifact_manifest_uri = btrim(artifact_manifest_uri) AND artifact_manifest_uri <> ''",
            name="ck_model_releases_manifest_uri_nonblank",
        ),
        sa.CheckConstraint(
            "artifact_manifest_hash ~ '^[0-9a-f]{64}$'", name="ck_model_releases_manifest_hash"
        ),
        sa.CheckConstraint(
            "input_schema_version = btrim(input_schema_version) AND input_schema_version <> ''",
            name="ck_model_releases_input_schema_nonblank",
        ),
        sa.CheckConstraint(
            "output_schema_version = btrim(output_schema_version) AND output_schema_version <> ''",
            name="ck_model_releases_output_schema_nonblank",
        ),
    )

    op.create_table(
        "prediction_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_snapshot_hash", sa.Text(), nullable=False),
        sa.Column("input_snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "status",
            postgresql.ENUM(*JOB_STATUSES, name="prediction_job_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.Text()),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_revision_id"],
            ["earthquake_event_revisions.event_revision_id"],
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_release_id"],
            ["model_releases.model_release_id"],
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "event_revision_id",
            "model_release_id",
            "input_snapshot_hash",
            name="uq_prediction_jobs_revision_release_snapshot",
        ),
        sa.CheckConstraint(
            "input_snapshot_hash ~ '^[0-9a-f]{64}$'", name="ck_prediction_jobs_hash"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(input_snapshot_json) = 'object'",
            name="ck_prediction_jobs_snapshot_object",
        ),
        sa.CheckConstraint(
            "idempotency_key = btrim(idempotency_key) AND idempotency_key <> ''",
            name="ck_prediction_jobs_idempotency_nonblank",
        ),
        sa.CheckConstraint(
            "(status = 'retry_wait' AND next_attempt_at IS NOT NULL) OR (status <> 'retry_wait' AND next_attempt_at IS NULL)",
            name="ck_prediction_jobs_retry_schedule",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL) OR (status IN ('pending', 'running', 'retry_wait') AND completed_at IS NULL)",
            name="ck_prediction_jobs_completion_state",
        ),
        sa.CheckConstraint(
            "(last_error_code IS NULL OR (last_error_code = btrim(last_error_code) AND last_error_code <> '')) AND (last_error_message IS NULL OR (last_error_message = btrim(last_error_message) AND last_error_message <> ''))",
            name="ck_prediction_jobs_errors_nonblank",
        ),
    )
    op.create_index("ix_prediction_jobs_model_release_id", "prediction_jobs", ["model_release_id"])
    op.create_index(
        "ix_prediction_jobs_revision_release_requested",
        "prediction_jobs",
        ["event_revision_id", "model_release_id", sa.text("requested_at DESC")],
    )

    op.create_table(
        "job_dispatches",
        sa.Column("dispatch_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), unique=True),
        sa.Column("prediction_job_id", postgresql.UUID(as_uuid=True), unique=True),
        sa.Column("alert_job_id", postgresql.UUID(as_uuid=True), unique=True),
        sa.Column(
            "status",
            postgresql.ENUM(*DISPATCH_STATUSES, name="dispatch_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("next_dispatch_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("dispatch_token", postgresql.UUID(as_uuid=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.run_id"],
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prediction_job_id"],
            ["prediction_jobs.job_id"],
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "num_nonnulls(ingestion_run_id, prediction_job_id, alert_job_id) = 1",
            name="ck_job_dispatches_exactly_one_target",
        ),
        sa.CheckConstraint("alert_job_id IS NULL", name="ck_job_dispatches_alert_target_deferred"),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_job_dispatches_attempt_count_nonnegative"
        ),
        sa.CheckConstraint(
            "(status = 'dispatching' AND next_dispatch_at IS NULL AND lease_expires_at IS NOT NULL AND dispatch_token IS NOT NULL) OR (status IN ('pending', 'retry_wait') AND next_dispatch_at IS NOT NULL AND lease_expires_at IS NULL AND dispatch_token IS NULL) OR (status IN ('enqueued', 'stopped') AND next_dispatch_at IS NULL AND lease_expires_at IS NULL AND dispatch_token IS NULL)",
            name="ck_job_dispatches_state_claim",
        ),
        sa.CheckConstraint(
            "last_error IS NULL OR (last_error = btrim(last_error) AND last_error <> '')",
            name="ck_job_dispatches_last_error_nonblank",
        ),
    )
    op.create_index(
        "ix_job_dispatches_ready",
        "job_dispatches",
        ["next_dispatch_at", "dispatch_id"],
        postgresql_where=sa.text("status IN ('pending', 'retry_wait')"),
    )
    op.create_index(
        "ix_job_dispatches_dispatching_lease",
        "job_dispatches",
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'dispatching'"),
    )


def downgrade() -> None:
    for table_name in (
        "job_dispatches",
        "prediction_jobs",
        "model_releases",
        "earthquake_event_revisions",
        "earthquake_events",
        "ingestion_runs",
    ):
        op.drop_table(table_name)
    bind = op.get_bind()
    postgresql.ENUM(*DISPATCH_STATUSES, name="dispatch_status").drop(bind)
    postgresql.ENUM(*JOB_STATUSES, name="prediction_job_status").drop(bind)
    postgresql.ENUM(*RUN_STATUSES, name="ingestion_run_status").drop(bind)
