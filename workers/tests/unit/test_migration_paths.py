"""Migrations and readiness checks resolve the same relocated revision chain."""

from pathlib import Path

from alembic.script import ScriptDirectory

from quakestrike.infrastructure.database.migration_state import worker_alembic_config


def test_migration_configuration_resolves_outside_the_worker_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    config = worker_alembic_config()
    database_directory = Path(__file__).resolve().parents[3] / "database"

    assert Path(config.config_file_name) == database_directory / "alembic.ini"
    script = ScriptDirectory.from_config(config)
    assert Path(script.dir) == database_directory / "migrations"
    assert script.get_current_head() == "20261011_13"
    assert script.get_revision("20260916_01").down_revision is None
