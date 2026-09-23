"""SQLAlchemy Core mappings for the Phase 2 ingestion foundation."""

# ruff: noqa: E501

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID

from quakestrike.infrastructure.database.metadata import metadata

INGESTION_RUN_STATUSES = (
    "pending",
    "running",
    "retry_wait",
    "succeeded",
    "failed",
    "cancelled",
)
PREDICTION_JOB_STATUSES = INGESTION_RUN_STATUSES
DISPATCH_STATUSES = ("pending", "dispatching", "enqueued", "retry_wait", "stopped")
PREDICTION_ATTEMPT_STATUSES = ("running", "succeeded", "failed", "abandoned")
ALERT_JOB_STATUSES = (
    "pending",
    "resolving",
    "delivering",
    "completed",
    "failed",
    "expired",
)

ingestion_run_status = ENUM(*INGESTION_RUN_STATUSES, name="ingestion_run_status", create_type=False)
prediction_job_status = ENUM(
    *PREDICTION_JOB_STATUSES, name="prediction_job_status", create_type=False
)
dispatch_status = ENUM(*DISPATCH_STATUSES, name="dispatch_status", create_type=False)
prediction_attempt_status = ENUM(
    *PREDICTION_ATTEMPT_STATUSES, name="prediction_attempt_status", create_type=False
)
alert_job_status = ENUM(*ALERT_JOB_STATUSES, name="alert_job_status", create_type=False)

FEATURE_SNAPSHOT_SCHEMA_VERSION = "quakestrike.prediction-input.v1"
FEATURE_SNAPSHOT_KEYS = (
    "anchor_magnitude",
    "anchor_depth_km",
    "anchor_latitude",
    "anchor_longitude",
    "anchor_time_is_minute_precision",
    "catalog_m1_plus_count_past_1h",
    "catalog_m1_plus_count_past_24h",
    "catalog_m1_plus_count_past_7d",
    "local_m1_plus_count_past_24h_within_50km",
    "local_m1_plus_count_past_24h_within_100km",
)
_FEATURE_SNAPSHOT_KEYS_ARRAY = (
    "ARRAY[" + ", ".join(f"'{key}'" for key in FEATURE_SNAPSHOT_KEYS) + "]"
)


def _nonblank(column: str) -> str:
    return f"{column} = btrim({column}) AND {column} <> ''"


ingestion_runs = Table(
    "ingestion_runs",
    metadata,
    Column("run_id", UUID(as_uuid=True), primary_key=True),
    Column("trigger_type", Text, nullable=False),
    Column("status", ingestion_run_status, nullable=False, server_default="pending"),
    Column("requested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("started_at", DateTime(timezone=True)),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("next_attempt_at", DateTime(timezone=True)),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("worker_execution_id", UUID(as_uuid=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("events_found", Integer, nullable=False, server_default="0"),
    Column("events_inserted", Integer, nullable=False, server_default="0"),
    Column("events_revised", Integer, nullable=False, server_default="0"),
    Column("events_unchanged", Integer, nullable=False, server_default="0"),
    Column("events_rejected", Integer, nullable=False, server_default="0"),
    Column("error_code", Text),
    Column("error_message", Text),
    Column("correlation_id", UUID(as_uuid=True), nullable=False),
    Column("bootstrap_snapshot_sha256", Text),
    Column("bootstrap_enriched_snapshot_sha256", Text),
    CheckConstraint(
        "trigger_type IN ('scheduled', 'manual', 'backfill')", name="ck_ingestion_runs_trigger_type"
    ),
    CheckConstraint("attempt_count >= 0", name="ck_ingestion_runs_attempt_count_nonnegative"),
    CheckConstraint(
        "events_found >= 0 AND events_inserted >= 0 AND events_revised >= 0 "
        "AND events_unchanged >= 0 AND events_rejected >= 0",
        name="ck_ingestion_runs_counters_nonnegative",
    ),
    CheckConstraint(
        "(error_code IS NULL OR (error_code = btrim(error_code) AND error_code <> '')) "
        "AND (error_message IS NULL OR "
        "(error_message = btrim(error_message) AND error_message <> ''))",
        name="ck_ingestion_runs_errors_nonblank",
    ),
    CheckConstraint(
        "(status = 'running' AND started_at IS NOT NULL AND lease_expires_at IS NOT NULL "
        "AND worker_execution_id IS NOT NULL AND finished_at IS NULL) OR "
        "(status <> 'running' AND lease_expires_at IS NULL AND worker_execution_id IS NULL)",
        name="ck_ingestion_runs_running_lease",
    ),
    CheckConstraint(
        "(status IN ('succeeded', 'failed', 'cancelled') AND finished_at IS NOT NULL) OR "
        "(status IN ('pending', 'running', 'retry_wait') AND finished_at IS NULL)",
        name="ck_ingestion_runs_finished_state",
    ),
    CheckConstraint(
        "(status = 'retry_wait' AND next_attempt_at IS NOT NULL) OR "
        "(status <> 'retry_wait' AND next_attempt_at IS NULL)",
        name="ck_ingestion_runs_retry_schedule",
    ),
    CheckConstraint(
        "status <> 'pending' OR started_at IS NULL",
        name="ck_ingestion_runs_pending_not_started",
    ),
    CheckConstraint(
        "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
        name="ck_ingestion_runs_finish_order",
    ),
    CheckConstraint(
        "(trigger_type <> 'backfill' AND bootstrap_snapshot_sha256 IS NULL "
        "AND bootstrap_enriched_snapshot_sha256 IS NULL) OR "
        "(trigger_type = 'backfill' AND bootstrap_snapshot_sha256 IS NOT NULL "
        "AND bootstrap_snapshot_sha256 ~ '^[0-9a-f]{64}$' "
        "AND (bootstrap_enriched_snapshot_sha256 IS NULL OR "
        "bootstrap_enriched_snapshot_sha256 ~ '^[0-9a-f]{64}$'))",
        name="ck_ingestion_runs_bootstrap_snapshot_hash",
    ),
)
Index(
    "ix_ingestion_runs_bootstrap_snapshot_sha256",
    ingestion_runs.c.bootstrap_snapshot_sha256,
    unique=True,
    postgresql_where=ingestion_runs.c.bootstrap_snapshot_sha256.is_not(None),
)
Index(
    "uq_ingestion_runs_one_active",
    ingestion_runs.c.status.is_not(None),
    unique=True,
    postgresql_where=ingestion_runs.c.status.in_(("pending", "running", "retry_wait")),
)
Index(
    "ix_ingestion_runs_running_lease",
    ingestion_runs.c.lease_expires_at,
    postgresql_where=ingestion_runs.c.status == "running",
)

earthquake_events = Table(
    "earthquake_events",
    metadata,
    Column("event_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "first_seen_run_id",
        UUID(as_uuid=True),
        ForeignKey("ingestion_runs.run_id", onupdate="RESTRICT", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "last_seen_run_id",
        UUID(as_uuid=True),
        ForeignKey("ingestion_runs.run_id", onupdate="RESTRICT", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "superseded_by_event_id",
        UUID(as_uuid=True),
        ForeignKey("earthquake_events.event_id", onupdate="RESTRICT", ondelete="RESTRICT"),
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "superseded_by_event_id IS NULL OR superseded_by_event_id <> event_id",
        name="ck_earthquake_events_no_self_supersession",
    ),
)
Index("ix_earthquake_events_first_seen_run_id", earthquake_events.c.first_seen_run_id)
Index("ix_earthquake_events_last_seen_run_id", earthquake_events.c.last_seen_run_id)
Index("ix_earthquake_events_superseded_by_event_id", earthquake_events.c.superseded_by_event_id)

earthquake_bulletin_event_identities = Table(
    "earthquake_bulletin_event_identities",
    metadata,
    Column("source_bulletin_id", Text, primary_key=True),
    Column(
        "event_id",
        UUID(as_uuid=True),
        ForeignKey("earthquake_events.event_id", onupdate="RESTRICT", ondelete="RESTRICT"),
        nullable=False,
    ),
    CheckConstraint(
        "source_bulletin_id = btrim(source_bulletin_id) "
        "AND source_bulletin_id <> '' AND source_bulletin_id = upper(source_bulletin_id)",
        name="ck_bulletin_event_identities_bulletin_id",
    ),
    UniqueConstraint(
        "source_bulletin_id",
        "event_id",
        name="uq_bulletin_event_identities_bulletin_event",
    ),
)
Index("ix_bulletin_event_identities_event_id", earthquake_bulletin_event_identities.c.event_id)

earthquake_event_revisions = Table(
    "earthquake_event_revisions",
    metadata,
    Column("event_revision_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "event_id",
        UUID(as_uuid=True),
        ForeignKey("earthquake_events.event_id", onupdate="RESTRICT", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("revision_number", Integer, nullable=False),
    Column(
        "ingestion_run_id",
        UUID(as_uuid=True),
        ForeignKey("ingestion_runs.run_id", onupdate="RESTRICT", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("source_bulletin_id", Text),
    Column("source_event_group_id", Text),
    Column("source_url", Text, nullable=False),
    Column("source_time_precision", Text, nullable=False),
    Column("event_time", DateTime(timezone=True), nullable=False),
    Column("latitude", Numeric(9, 6), nullable=False),
    Column("longitude", Numeric(10, 6), nullable=False),
    Column("depth_km", Numeric(10, 3), nullable=False),
    Column("magnitude", Numeric(5, 2), nullable=False),
    Column("location_description", Text, nullable=False),
    Column("origin", Text),
    Column("prediction_skip_reason", Text),
    Column("ingested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("event_id", "revision_number", name="uq_event_revisions_event_revision"),
    ForeignKeyConstraint(
        ["source_bulletin_id", "event_id"],
        [
            "earthquake_bulletin_event_identities.source_bulletin_id",
            "earthquake_bulletin_event_identities.event_id",
        ],
        onupdate="RESTRICT",
        ondelete="RESTRICT",
        name="fk_event_revisions_bulletin_event_identity",
    ),
    CheckConstraint("revision_number >= 1", name="ck_event_revisions_revision_number"),
    CheckConstraint(
        "source_bulletin_id IS NOT NULL OR source_event_group_id IS NOT NULL",
        name="ck_event_revisions_source_identifier",
    ),
    CheckConstraint(
        "source_bulletin_id IS NULL OR "
        "(source_bulletin_id = btrim(source_bulletin_id) AND source_bulletin_id <> '' "
        "AND source_bulletin_id = upper(source_bulletin_id))",
        name="ck_event_revisions_bulletin_id",
    ),
    CheckConstraint(
        "source_event_group_id IS NULL OR "
        "(source_event_group_id = btrim(source_event_group_id) AND source_event_group_id <> '' "
        "AND source_event_group_id = upper(source_event_group_id))",
        name="ck_event_revisions_group_id",
    ),
    CheckConstraint(_nonblank("source_url"), name="ck_event_revisions_source_url_nonblank"),
    CheckConstraint(
        "source_time_precision IN ('minute', 'second')",
        name="ck_event_revisions_time_precision",
    ),
    CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_event_revisions_latitude"),
    CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_event_revisions_longitude"),
    CheckConstraint("depth_km >= 0", name="ck_event_revisions_depth"),
    CheckConstraint(
        "latitude NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
        "AND longitude NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
        "AND depth_km NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
        "AND magnitude NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
        name="ck_event_revisions_observations_finite",
    ),
    CheckConstraint(_nonblank("location_description"), name="ck_event_revisions_location_nonblank"),
    CheckConstraint(
        "origin IS NULL OR origin IN ('TECTONIC', 'VOLCANIC', 'TECTONIC-VOLCANIC')",
        name="ck_event_revisions_origin",
    ),
    CheckConstraint(
        "prediction_skip_reason IS NULL OR prediction_skip_reason IN ("
        "'magnitude_below_m1', 'history_coverage_unavailable', "
        "'incomplete_feature_history', 'history_starts_after_required_window', "
        "'history_ends_before_anchor', 'model_release_unavailable')",
        name="ck_event_revisions_prediction_skip_reason",
    ),
)
Index(
    "ix_event_revisions_source_bulletin_id",
    earthquake_event_revisions.c.source_bulletin_id,
    postgresql_where=earthquake_event_revisions.c.source_bulletin_id.is_not(None),
)
Index(
    "ix_event_revisions_source_event_group_id",
    earthquake_event_revisions.c.source_event_group_id,
)
Index("ix_event_revisions_ingestion_run_id", earthquake_event_revisions.c.ingestion_run_id)
Index("ix_event_revisions_event_time", earthquake_event_revisions.c.event_time)

ingestion_run_inputs = Table(
    "ingestion_run_inputs",
    metadata,
    Column(
        "run_id",
        UUID(as_uuid=True),
        ForeignKey("ingestion_runs.run_id", onupdate="RESTRICT", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("input_key", Text, primary_key=True),
    Column("outcome", Text, nullable=False),
    Column(
        "event_id",
        UUID(as_uuid=True),
        ForeignKey("earthquake_events.event_id", onupdate="RESTRICT", ondelete="RESTRICT"),
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "input_key = btrim(input_key) AND input_key <> ''",
        name="ck_ingestion_run_inputs_key_nonblank",
    ),
    CheckConstraint(
        "outcome IN ('inserted', 'revised', 'unchanged', 'rejected')",
        name="ck_ingestion_run_inputs_outcome",
    ),
    CheckConstraint(
        "(outcome = 'rejected' AND event_id IS NULL) OR "
        "(outcome <> 'rejected' AND event_id IS NOT NULL)",
        name="ck_ingestion_run_inputs_outcome_event",
    ),
)
Index(
    "ix_ingestion_run_inputs_run_outcome",
    ingestion_run_inputs.c.run_id,
    ingestion_run_inputs.c.outcome,
)
Index("ix_ingestion_run_inputs_event_id", ingestion_run_inputs.c.event_id)

model_releases = Table(
    "model_releases",
    metadata,
    Column("model_release_id", UUID(as_uuid=True), primary_key=True),
    Column("version_label", Text, nullable=False, unique=True),
    Column("artifact_manifest_uri", Text, nullable=False),
    Column("artifact_manifest_hash", Text, nullable=False),
    Column("input_schema_version", Text, nullable=False),
    Column("output_schema_version", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(_nonblank("version_label"), name="ck_model_releases_version_label_nonblank"),
    CheckConstraint(
        _nonblank("artifact_manifest_uri"), name="ck_model_releases_manifest_uri_nonblank"
    ),
    CheckConstraint(
        "artifact_manifest_hash ~ '^[0-9a-f]{64}$'",
        name="ck_model_releases_manifest_hash",
    ),
    CheckConstraint(
        _nonblank("input_schema_version"), name="ck_model_releases_input_schema_nonblank"
    ),
    CheckConstraint(
        _nonblank("output_schema_version"), name="ck_model_releases_output_schema_nonblank"
    ),
)

prediction_jobs = Table(
    "prediction_jobs",
    metadata,
    Column("job_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "event_revision_id",
        UUID(as_uuid=True),
        ForeignKey(
            "earthquake_event_revisions.event_revision_id",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "model_release_id",
        UUID(as_uuid=True),
        ForeignKey("model_releases.model_release_id", onupdate="RESTRICT", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("input_snapshot_hash", Text, nullable=False),
    Column("input_snapshot_json", JSONB, nullable=False),
    Column("idempotency_key", Text, nullable=False, unique=True),
    Column("status", prediction_job_status, nullable=False, server_default="pending"),
    Column("requested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("next_attempt_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("last_error_code", Text),
    Column("last_error_message", Text),
    Column("correlation_id", UUID(as_uuid=True), nullable=False),
    UniqueConstraint(
        "event_revision_id",
        "model_release_id",
        "input_snapshot_hash",
        name="uq_prediction_jobs_revision_release_snapshot",
    ),
    CheckConstraint("input_snapshot_hash ~ '^[0-9a-f]{64}$'", name="ck_prediction_jobs_hash"),
    CheckConstraint(
        "jsonb_typeof(input_snapshot_json) = 'object'",
        name="ck_prediction_jobs_snapshot_object",
    ),
    CheckConstraint(
        "CASE WHEN jsonb_typeof(input_snapshot_json) = 'object' THEN "
        f"input_snapshot_json ?& {_FEATURE_SNAPSHOT_KEYS_ARRAY} "
        f"AND input_snapshot_json - {_FEATURE_SNAPSHOT_KEYS_ARRAY} = '{{}}'::jsonb "
        "ELSE FALSE END",
        name="ck_prediction_jobs_snapshot_keys",
    ),
    CheckConstraint(
        "CASE WHEN jsonb_typeof(input_snapshot_json -> 'anchor_magnitude') = 'number' THEN "
        "(input_snapshot_json ->> 'anchor_magnitude')::numeric NOT IN "
        "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
        "AND (input_snapshot_json ->> 'anchor_magnitude')::numeric BETWEEN -999.99 AND 999.99 "
        "ELSE FALSE END "
        "AND CASE WHEN jsonb_typeof(input_snapshot_json -> 'anchor_depth_km') = 'number' THEN "
        "(input_snapshot_json ->> 'anchor_depth_km')::numeric NOT IN "
        "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
        "AND (input_snapshot_json ->> 'anchor_depth_km')::numeric BETWEEN 0 AND 9999999.999 "
        "ELSE FALSE END "
        "AND CASE WHEN jsonb_typeof(input_snapshot_json -> 'anchor_latitude') = 'number' THEN "
        "(input_snapshot_json ->> 'anchor_latitude')::numeric NOT IN "
        "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
        "AND (input_snapshot_json ->> 'anchor_latitude')::numeric BETWEEN -90 AND 90 "
        "ELSE FALSE END "
        "AND CASE WHEN jsonb_typeof(input_snapshot_json -> 'anchor_longitude') = 'number' THEN "
        "(input_snapshot_json ->> 'anchor_longitude')::numeric NOT IN "
        "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
        "AND (input_snapshot_json ->> 'anchor_longitude')::numeric BETWEEN -180 AND 180 "
        "ELSE FALSE END "
        "AND CASE WHEN jsonb_typeof(input_snapshot_json -> "
        "'anchor_time_is_minute_precision') = 'number' THEN "
        "(input_snapshot_json ->> 'anchor_time_is_minute_precision') ~ '^[01]$' "
        "ELSE FALSE END "
        "AND CASE WHEN jsonb_typeof(input_snapshot_json -> "
        "'catalog_m1_plus_count_past_1h') = 'number' THEN "
        "(input_snapshot_json ->> 'catalog_m1_plus_count_past_1h') ~ '^[0-9]+$' "
        "ELSE FALSE END "
        "AND CASE WHEN jsonb_typeof(input_snapshot_json -> "
        "'catalog_m1_plus_count_past_24h') = 'number' THEN "
        "(input_snapshot_json ->> 'catalog_m1_plus_count_past_24h') ~ '^[0-9]+$' "
        "ELSE FALSE END "
        "AND CASE WHEN jsonb_typeof(input_snapshot_json -> "
        "'catalog_m1_plus_count_past_7d') = 'number' THEN "
        "(input_snapshot_json ->> 'catalog_m1_plus_count_past_7d') ~ '^[0-9]+$' "
        "ELSE FALSE END "
        "AND CASE WHEN jsonb_typeof(input_snapshot_json -> "
        "'local_m1_plus_count_past_24h_within_50km') = 'number' THEN "
        "(input_snapshot_json ->> 'local_m1_plus_count_past_24h_within_50km') ~ '^[0-9]+$' "
        "ELSE FALSE END "
        "AND CASE WHEN jsonb_typeof(input_snapshot_json -> "
        "'local_m1_plus_count_past_24h_within_100km') = 'number' THEN "
        "(input_snapshot_json ->> 'local_m1_plus_count_past_24h_within_100km') ~ '^[0-9]+$' "
        "ELSE FALSE END",
        name="ck_prediction_jobs_snapshot_value_types",
    ),
    CheckConstraint(
        "input_snapshot_hash = quakestrike_prediction_input_snapshot_sha256(input_snapshot_json)",
        name="ck_prediction_jobs_snapshot_hash",
    ),
    CheckConstraint(_nonblank("idempotency_key"), name="ck_prediction_jobs_idempotency_nonblank"),
    CheckConstraint(
        "(status = 'retry_wait' AND next_attempt_at IS NOT NULL) OR "
        "(status <> 'retry_wait' AND next_attempt_at IS NULL)",
        name="ck_prediction_jobs_retry_schedule",
    ),
    CheckConstraint(
        "(status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL) OR "
        "(status IN ('pending', 'running', 'retry_wait') AND completed_at IS NULL)",
        name="ck_prediction_jobs_completion_state",
    ),
    CheckConstraint(
        "(last_error_code IS NULL OR (last_error_code = btrim(last_error_code) "
        "AND last_error_code <> '')) AND "
        "(last_error_message IS NULL OR (last_error_message = btrim(last_error_message) "
        "AND last_error_message <> ''))",
        name="ck_prediction_jobs_errors_nonblank",
    ),
)
Index("ix_prediction_jobs_model_release_id", prediction_jobs.c.model_release_id)
Index(
    "ix_prediction_jobs_revision_release_requested",
    prediction_jobs.c.event_revision_id,
    prediction_jobs.c.model_release_id,
    prediction_jobs.c.requested_at.desc(),
)

job_dispatches = Table(
    "job_dispatches",
    metadata,
    Column("dispatch_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "ingestion_run_id",
        UUID(as_uuid=True),
        ForeignKey("ingestion_runs.run_id", onupdate="RESTRICT", ondelete="RESTRICT"),
        unique=True,
    ),
    Column(
        "prediction_job_id",
        UUID(as_uuid=True),
        ForeignKey("prediction_jobs.job_id", onupdate="RESTRICT", ondelete="RESTRICT"),
        unique=True,
    ),
    Column(
        "alert_job_id",
        UUID(as_uuid=True),
        ForeignKey("alert_jobs.alert_job_id", onupdate="RESTRICT", ondelete="RESTRICT"),
        unique=True,
    ),
    Column("status", dispatch_status, nullable=False, server_default="pending"),
    Column("next_dispatch_at", DateTime(timezone=True), server_default=func.now()),
    Column("last_dispatched_at", DateTime(timezone=True)),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("dispatch_token", UUID(as_uuid=True)),
    Column("last_error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "num_nonnulls(ingestion_run_id, prediction_job_id, alert_job_id) = 1",
        name="ck_job_dispatches_exactly_one_target",
    ),
    CheckConstraint("attempt_count >= 0", name="ck_job_dispatches_attempt_count_nonnegative"),
    CheckConstraint(
        "(status = 'dispatching' AND next_dispatch_at IS NULL "
        "AND lease_expires_at IS NOT NULL AND dispatch_token IS NOT NULL) OR "
        "(status IN ('pending', 'retry_wait') AND next_dispatch_at IS NOT NULL "
        "AND lease_expires_at IS NULL AND dispatch_token IS NULL) OR "
        "(status IN ('enqueued', 'stopped') AND next_dispatch_at IS NULL "
        "AND lease_expires_at IS NULL AND dispatch_token IS NULL)",
        name="ck_job_dispatches_state_claim",
    ),
    CheckConstraint(
        "last_error IS NULL OR (last_error = btrim(last_error) AND last_error <> '')",
        name="ck_job_dispatches_last_error_nonblank",
    ),
)
Index(
    "ix_job_dispatches_ready",
    job_dispatches.c.next_dispatch_at,
    job_dispatches.c.dispatch_id,
    postgresql_where=job_dispatches.c.status.in_(("pending", "retry_wait")),
)

prediction_attempts = Table(
    "prediction_attempts",
    metadata,
    Column("attempt_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "job_id",
        UUID(as_uuid=True),
        ForeignKey("prediction_jobs.job_id", onupdate="RESTRICT", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("attempt_number", Integer, nullable=False),
    Column("status", prediction_attempt_status, nullable=False, server_default="running"),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("worker_execution_id", UUID(as_uuid=True), nullable=False),
    Column("error_code", Text),
    Column("error_message", Text),
    UniqueConstraint("job_id", "attempt_number", name="uq_prediction_attempts_job_number"),
    CheckConstraint("attempt_number >= 1", name="ck_prediction_attempts_number"),
    CheckConstraint(
        "(status = 'running' AND lease_expires_at IS NOT NULL AND finished_at IS NULL) OR "
        "(status <> 'running' AND lease_expires_at IS NULL AND finished_at IS NOT NULL)",
        name="ck_prediction_attempts_state",
    ),
    CheckConstraint(
        "finished_at IS NULL OR finished_at >= started_at",
        name="ck_prediction_attempts_finish_order",
    ),
    CheckConstraint(
        "(error_code IS NULL OR (error_code = btrim(error_code) AND error_code <> '')) AND "
        "(error_message IS NULL OR (error_message = btrim(error_message) AND error_message <> ''))",
        name="ck_prediction_attempts_errors_nonblank",
    ),
)
Index(
    "uq_prediction_attempts_one_running",
    prediction_attempts.c.job_id,
    unique=True,
    postgresql_where=prediction_attempts.c.status == "running",
)
Index(
    "ix_prediction_attempts_running_lease",
    prediction_attempts.c.lease_expires_at,
    postgresql_where=prediction_attempts.c.status == "running",
)

forecasts = Table(
    "forecasts",
    metadata,
    Column("forecast_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "job_id",
        UUID(as_uuid=True),
        ForeignKey("prediction_jobs.job_id", onupdate="RESTRICT", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column(
        "supersedes_forecast_id",
        UUID(as_uuid=True),
        ForeignKey("forecasts.forecast_id", onupdate="RESTRICT", ondelete="RESTRICT"),
    ),
    Column("window_start", DateTime(timezone=True), nullable=False),
    Column("window_end", DateTime(timezone=True), nullable=False),
    Column("probability_m1_plus_24h", Double, nullable=False),
    Column("expected_m1_plus_count_24h", Double, nullable=False),
    Column("probability_m4_plus_24h", Double, nullable=False),
    Column("probability_m5_plus_24h", Double, nullable=False),
    Column("activity_radius_median_km_24h", Double),
    Column("maximum_magnitude_q05_24h", Double),
    Column("maximum_magnitude_q50_24h", Double),
    Column("maximum_magnitude_q95_24h", Double),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "window_end = window_start + interval '24 hours'", name="ck_forecasts_24h_window"
    ),
    CheckConstraint(
        "probability_m1_plus_24h BETWEEN 0 AND 1 AND probability_m4_plus_24h BETWEEN 0 AND 1 "
        "AND probability_m5_plus_24h BETWEEN 0 AND 1 "
        "AND probability_m5_plus_24h <= probability_m4_plus_24h "
        "AND probability_m4_plus_24h <= probability_m1_plus_24h",
        name="ck_forecasts_probabilities",
    ),
    CheckConstraint(
        "probability_m1_plus_24h < 'Infinity'::double precision "
        "AND probability_m1_plus_24h > '-Infinity'::double precision "
        "AND probability_m4_plus_24h < 'Infinity'::double precision "
        "AND probability_m4_plus_24h > '-Infinity'::double precision "
        "AND probability_m5_plus_24h < 'Infinity'::double precision "
        "AND probability_m5_plus_24h > '-Infinity'::double precision "
        "AND expected_m1_plus_count_24h < 'Infinity'::double precision "
        "AND expected_m1_plus_count_24h > '-Infinity'::double precision "
        "AND (activity_radius_median_km_24h IS NULL OR (activity_radius_median_km_24h < 'Infinity'::double precision AND activity_radius_median_km_24h > '-Infinity'::double precision)) "
        "AND (maximum_magnitude_q05_24h IS NULL OR (maximum_magnitude_q05_24h < 'Infinity'::double precision AND maximum_magnitude_q05_24h > '-Infinity'::double precision)) "
        "AND (maximum_magnitude_q50_24h IS NULL OR (maximum_magnitude_q50_24h < 'Infinity'::double precision AND maximum_magnitude_q50_24h > '-Infinity'::double precision)) "
        "AND (maximum_magnitude_q95_24h IS NULL OR (maximum_magnitude_q95_24h < 'Infinity'::double precision AND maximum_magnitude_q95_24h > '-Infinity'::double precision))",
        name="ck_forecasts_finite_outputs",
    ),
    CheckConstraint("expected_m1_plus_count_24h >= 0", name="ck_forecasts_expected_count"),
    CheckConstraint(
        "activity_radius_median_km_24h IS NULL OR activity_radius_median_km_24h >= 0",
        name="ck_forecasts_radius",
    ),
    CheckConstraint(
        "(maximum_magnitude_q05_24h IS NULL AND maximum_magnitude_q50_24h IS NULL AND maximum_magnitude_q95_24h IS NULL) OR "
        "(maximum_magnitude_q05_24h IS NOT NULL AND maximum_magnitude_q50_24h IS NOT NULL AND maximum_magnitude_q95_24h IS NOT NULL "
        "AND maximum_magnitude_q05_24h <= maximum_magnitude_q50_24h AND maximum_magnitude_q50_24h <= maximum_magnitude_q95_24h)",
        name="ck_forecasts_quantiles",
    ),
    CheckConstraint(
        "supersedes_forecast_id IS NULL OR supersedes_forecast_id <> forecast_id",
        name="ck_forecasts_supersedes_other",
    ),
)
Index("ix_forecasts_supersedes_forecast_id", forecasts.c.supersedes_forecast_id)

alert_jobs = Table(
    "alert_jobs",
    metadata,
    Column("alert_job_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "forecast_id",
        UUID(as_uuid=True),
        ForeignKey("forecasts.forecast_id", onupdate="RESTRICT", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("requested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("message_snapshot", Text, nullable=False),
    Column("recipient_policy_snapshot", JSONB, nullable=False),
    Column("status", alert_job_status, nullable=False, server_default="pending"),
    Column("recipient_resolution_completed_at", DateTime(timezone=True)),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("worker_execution_id", UUID(as_uuid=True)),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    Column("correlation_id", UUID(as_uuid=True), nullable=False),
    CheckConstraint(
        "message_snapshot = btrim(message_snapshot) AND message_snapshot <> ''",
        name="ck_alert_jobs_message",
    ),
    CheckConstraint(
        "jsonb_typeof(recipient_policy_snapshot) = 'object'",
        name="ck_alert_jobs_recipient_policy_object",
    ),
    CheckConstraint("expires_at > requested_at", name="ck_alert_jobs_expiry"),
    CheckConstraint(
        "(status IN ('resolving', 'delivering') AND lease_expires_at IS NOT NULL AND worker_execution_id IS NOT NULL) OR "
        "(status NOT IN ('resolving', 'delivering') AND lease_expires_at IS NULL AND worker_execution_id IS NULL)",
        name="ck_alert_jobs_lease",
    ),
    CheckConstraint(
        "(status IN ('completed', 'failed', 'expired') AND completed_at IS NOT NULL) OR "
        "(status IN ('pending', 'resolving', 'delivering') AND completed_at IS NULL)",
        name="ck_alert_jobs_completion",
    ),
)
Index("ix_alert_jobs_status_expiry", alert_jobs.c.status, alert_jobs.c.expires_at)
Index("ix_alert_jobs_requested_at", alert_jobs.c.requested_at)
Index(
    "ix_alert_jobs_active_lease",
    alert_jobs.c.lease_expires_at,
    postgresql_where=alert_jobs.c.status.in_(("resolving", "delivering")),
)

audit_logs = Table(
    "audit_logs",
    metadata,
    Column("audit_id", UUID(as_uuid=True), primary_key=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("actor_type", Text, nullable=False),
    Column("actor_user_id", UUID(as_uuid=True)),
    Column("actor_service", Text),
    Column("action", Text, nullable=False),
    Column("target_type", Text),
    Column("target_id", Text),
    Column("target_revision", Text),
    Column("outcome", Text, nullable=False),
    Column("reason_code", Text),
    Column("request_id", UUID(as_uuid=True)),
    Column("correlation_id", UUID(as_uuid=True), nullable=False),
    Column("metadata", JSONB),
    CheckConstraint(
        "actor_type IN ('user', 'system', 'anonymous')", name="ck_audit_logs_actor_type"
    ),
    CheckConstraint("outcome IN ('succeeded', 'denied', 'failed')", name="ck_audit_logs_outcome"),
    CheckConstraint(
        "(actor_type = 'user' AND actor_user_id IS NOT NULL AND actor_service IS NULL) OR (actor_type = 'system' AND actor_user_id IS NULL AND actor_service IS NOT NULL) OR (actor_type = 'anonymous' AND actor_user_id IS NULL AND actor_service IS NULL)",
        name="ck_audit_logs_actor_identity",
    ),
    CheckConstraint(
        "(target_type IS NULL AND target_id IS NULL) OR (target_type IS NOT NULL AND target_id IS NOT NULL)",
        name="ck_audit_logs_target_pair",
    ),
    CheckConstraint(
        "action = btrim(action) AND action <> '' AND "
        "(actor_service IS NULL OR (actor_service = btrim(actor_service) AND actor_service <> '')) AND "
        "(target_type IS NULL OR (target_type = btrim(target_type) AND target_type <> '')) AND "
        "(target_id IS NULL OR (target_id = btrim(target_id) AND target_id <> '')) AND "
        "(target_revision IS NULL OR (target_revision = btrim(target_revision) AND target_revision <> '')) AND "
        "(reason_code IS NULL OR (reason_code = btrim(reason_code) AND reason_code <> ''))",
        name="ck_audit_logs_identifiers_nonblank",
    ),
    CheckConstraint("jsonb_typeof(metadata) = 'object'", name="ck_audit_logs_metadata_object"),
    CheckConstraint("actor_type <> 'user'", name="ck_audit_logs_user_actor_deferred"),
)
Index("ix_audit_logs_occurred_at", audit_logs.c.occurred_at)
Index("ix_audit_logs_actor_occurred_at", audit_logs.c.actor_user_id, audit_logs.c.occurred_at)
Index(
    "ix_audit_logs_target_occurred_at",
    audit_logs.c.target_type,
    audit_logs.c.target_id,
    audit_logs.c.occurred_at,
)
Index("ix_audit_logs_correlation_id", audit_logs.c.correlation_id)
Index(
    "ix_job_dispatches_dispatching_lease",
    job_dispatches.c.lease_expires_at,
    postgresql_where=job_dispatches.c.status == "dispatching",
)
