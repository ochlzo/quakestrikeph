from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text


def _database_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL")
    if value is None:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests.")
    return value


def alembic_config() -> Config:
    workers_directory = Path(__file__).resolve().parents[2]
    config = Config(str(workers_directory / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", _database_url().replace("%", "%%"))
    return config


@pytest.fixture(scope="session")
def migrated_engine() -> Iterator[Engine]:
    config = alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(_database_url())
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(migrated_engine: Engine) -> Iterator[None]:
    yield
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE maintenance_runs, source_catalog_evidence, ingestion_run_inputs, "
                "earthquake_bulletin_event_identities, "
                "audit_logs, users, job_dispatches, prediction_jobs, model_releases, "
                "earthquake_event_revisions, "
                "earthquake_events, ingestion_runs CASCADE"
            )
        )
