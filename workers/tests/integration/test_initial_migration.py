from __future__ import annotations

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from quakestrike.infrastructure.database.migration_state import AlembicMigrationStateGate
from quakestrike.infrastructure.settings import Settings

from .conftest import alembic_config

pytestmark = __import__("pytest").mark.integration

EXPECTED_TABLES = {
    "alembic_version",
    "ingestion_runs",
    "source_catalog_evidence",
    "earthquake_events",
    "earthquake_bulletin_event_identities",
    "earthquake_event_revisions",
    "ingestion_run_inputs",
    "model_releases",
    "prediction_jobs",
    "job_dispatches",
    "prediction_attempts",
    "forecasts",
    "alert_jobs",
    "audit_logs",
    "maintenance_runs",
}
EXPECTED_ENUMS = {
    "ingestion_run_status",
    "prediction_job_status",
    "dispatch_status",
    "prediction_attempt_status",
    "alert_job_status",
    "maintenance_run_status",
}


def _settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        database_url=database_url,
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/catalog",
        model_release_id="00000000-0000-0000-0000-000000000001",
    )


def test_upgrade_creates_only_phase_two_schema_and_uuid_keys_have_no_defaults(
    migrated_engine,
) -> None:
    inspector = inspect(migrated_engine)
    assert set(inspector.get_table_names()) == EXPECTED_TABLES
    assert {item["name"] for item in inspector.get_enums()} == EXPECTED_ENUMS
    dispatch_foreign_keys = {
        tuple(item["constrained_columns"]): item["referred_table"]
        for item in inspector.get_foreign_keys("job_dispatches")
    }
    assert dispatch_foreign_keys[("alert_job_id",)] == "alert_jobs"
    assert {column["name"] for column in inspector.get_columns("alert_jobs")} == {
        "alert_job_id",
        "forecast_id",
        "requested_at",
        "message_snapshot",
        "recipient_policy_snapshot",
        "status",
        "recipient_resolution_completed_at",
        "lease_expires_at",
        "worker_execution_id",
        "expires_at",
        "completed_at",
        "correlation_id",
    }
    assert {item["name"] for item in inspector.get_indexes("alert_jobs")} >= {
        "ix_alert_jobs_active_lease",
        "ix_alert_jobs_requested_at",
        "ix_alert_jobs_status_expiry",
    }
    assert {item["name"] for item in inspector.get_indexes("audit_logs")} >= {
        "ix_audit_logs_actor_occurred_at",
        "ix_audit_logs_correlation_id",
        "ix_audit_logs_occurred_at",
        "ix_audit_logs_target_occurred_at",
    }

    for table_name, key_name in {
        "ingestion_runs": "run_id",
        "earthquake_events": "event_id",
        "earthquake_event_revisions": "event_revision_id",
        "model_releases": "model_release_id",
        "prediction_jobs": "job_id",
        "job_dispatches": "dispatch_id",
    }.items():
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert columns[key_name]["default"] is None


def test_downgrade_removes_tables_and_enums_then_upgrade_succeeds(migrated_engine) -> None:
    config = alembic_config()
    command.downgrade(config, "base")
    inspector = inspect(migrated_engine)
    assert set(inspector.get_table_names()) == {"alembic_version"}
    assert {item["name"] for item in inspector.get_enums()} == set()

    command.upgrade(config, "head")
    assert set(inspect(migrated_engine).get_table_names()) == EXPECTED_TABLES


def test_migration_gate_is_ready_at_head_and_read_only_when_revision_is_stale(
    migrated_engine,
) -> None:
    settings = _settings(str(migrated_engine.url))
    ready = AlembicMigrationStateGate(settings, engine=migrated_engine).check()
    assert ready.ready is True
    assert ready.details["current_revision"] == "20260925_09"

    with migrated_engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'stale_revision'"))
    stale = AlembicMigrationStateGate(settings, engine=migrated_engine).check()
    assert stale.ready is False
    with migrated_engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version")) == "stale_revision"
        )
    with migrated_engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '20260925_09'"))


def test_maintenance_evidence_requires_artifact_and_restore_link(migrated_engine) -> None:
    backup_id = uuid4()
    restore_id = uuid4()
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO maintenance_runs
                (maintenance_run_id, operation_type, status, target, correlation_id, finished_at)
                VALUES (:id, 'backup', 'succeeded', 'b2', :id, now())"""),
            {"id": backup_id},
        )

    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO maintenance_runs
                (maintenance_run_id, operation_type, status, target, correlation_id,
                 finished_at, artifact_reference)
                VALUES (:id, 'backup', 'succeeded', 'b2', :id, now(), :ref)"""),
            {"id": backup_id, "ref": "restic snapshot:abc"},
        )

    with migrated_engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO maintenance_runs
                (maintenance_run_id, operation_type, status, target, correlation_id,
                 finished_at, artifact_reference, artifact_checksum)
                VALUES (:id, 'backup', 'succeeded', 'b2', :id, now(), :ref, :checksum)"""),
            {"id": backup_id, "ref": "restic snapshot:abc", "checksum": "a" * 64},
        )
        connection.execute(
            text("""INSERT INTO maintenance_runs
                (maintenance_run_id, operation_type, status, target, correlation_id,
                 related_backup_run_id, finished_at, verification_summary)
                VALUES (:id, 'restore_test', 'succeeded', 'isolated', :id,
                        :backup_id, now(), 'checksums and rows verified')"""),
            {"id": restore_id, "backup_id": backup_id},
        )
        assert connection.scalar(text("SELECT count(*) FROM maintenance_runs")) == 2
        assert "public.digest(" in connection.scalar(
            text(
                "SELECT pg_get_functiondef("
                "'quakestrike_prediction_input_snapshot_sha256(jsonb)'::regprocedure)"
            )
        )
