from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from quakestrike.infrastructure.settings import Settings
from quakestrike.runtime import run_service

pytestmark = pytest.mark.integration


def test_failed_service_startup_leaves_schema_and_business_records_unchanged(
    migrated_engine, tmp_path
) -> None:
    settings = Settings(
        _env_file=None,
        database_url=migrated_engine.url.render_as_string(hide_password=False),
        redis_url=os.environ["TEST_REDIS_URL"],
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id="00000000-0000-0000-0000-000000000001",
        model_artifact_directory=tmp_path / "missing-model",
        bootstrap_run_manifest=tmp_path / "missing-bootstrap.json",
    )

    def snapshot() -> tuple[str, int, int, int]:
        with migrated_engine.connect() as connection:
            return (
                connection.scalar(text("SELECT version_num FROM alembic_version")),
                connection.scalar(text("SELECT count(*) FROM model_releases")),
                connection.scalar(text("SELECT count(*) FROM ingestion_runs")),
                connection.scalar(text("SELECT count(*) FROM job_dispatches")),
            )

    before = snapshot()
    for service in ("scheduler-dispatcher", "data-ingestor", "scheduler-beat"):
        started: list[str] = []
        assert (
            run_service(
                service,
                settings_factory=lambda: settings,
                runtime=lambda _, started=started, service=service: started.append(service) or 0,
            )
            == 2
        )
        assert started == []
        assert snapshot() == before
    assert not settings.bootstrap_run_manifest.exists()
