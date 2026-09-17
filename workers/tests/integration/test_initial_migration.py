from __future__ import annotations

from alembic import command
from sqlalchemy import inspect, text

from quakestrike.infrastructure.database.migration_state import AlembicMigrationStateGate
from quakestrike.infrastructure.settings import Settings

from .conftest import alembic_config

pytestmark = __import__("pytest").mark.integration

EXPECTED_TABLES = {
    "alembic_version",
    "ingestion_runs",
    "earthquake_events",
    "earthquake_event_revisions",
    "model_releases",
    "prediction_jobs",
    "job_dispatches",
}
EXPECTED_ENUMS = {"ingestion_run_status", "prediction_job_status", "dispatch_status"}


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
    assert ready.details["current_revision"] == "20260917_04"

    with migrated_engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'stale_revision'"))
    stale = AlembicMigrationStateGate(settings, engine=migrated_engine).check()
    assert stale.ready is False
    with migrated_engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version")) == "stale_revision"
        )
    with migrated_engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '20260917_04'"))
