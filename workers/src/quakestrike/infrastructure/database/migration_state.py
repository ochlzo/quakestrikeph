"""Read-only Alembic revision startup gate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine

from quakestrike.application.startup import GateResult
from quakestrike.infrastructure.database.engine import create_database_engine
from quakestrike.infrastructure.settings import Settings


def worker_alembic_config() -> Config:
    workers_directory = Path(__file__).resolve().parents[4]
    return Config(str(workers_directory.parent / "database" / "alembic.ini"))


@dataclass(frozen=True, slots=True)
class AlembicMigrationStateGate:
    settings: Settings
    engine: Engine | None = None

    name: str = "migration-state"

    def check(self) -> GateResult:
        engine = self.engine or create_database_engine(self.settings.database_url)
        owns_engine = self.engine is None
        try:
            expected_heads = tuple(ScriptDirectory.from_config(worker_alembic_config()).get_heads())
            with engine.connect() as connection:
                current_heads = tuple(MigrationContext.configure(connection).get_current_heads())
        except Exception as error:
            return GateResult(
                name=self.name,
                ready=False,
                reason="The database migration state could not be read.",
                details={"error_type": type(error).__name__},
            )
        finally:
            if owns_engine:
                engine.dispose()

        ready = current_heads == expected_heads
        return GateResult(
            name=self.name,
            ready=ready,
            reason=(
                "The database is at the required Alembic revision."
                if ready
                else "The database is missing the required Alembic revision."
            ),
            details={
                "current_revision": ",".join(current_heads) or "none",
                "required_revision": ",".join(expected_heads) or "none",
            },
        )
