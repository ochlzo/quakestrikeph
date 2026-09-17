"""Phase 1 startup adapters that deliberately report unavailable gates."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from quakestrike.application.startup import GateResult, StartupGate
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.database.migration_state import AlembicMigrationStateGate
from quakestrike.infrastructure.database.model_releases import SqlAlchemyModelReleaseRegistry
from quakestrike.infrastructure.health import (
    PostgresConnectivityHealthCheck,
    RedisConnectivityHealthCheck,
)
from quakestrike.infrastructure.models.release_manifest import (
    SELECTED_RELEASE_MANIFEST_URI,
    ManifestValidationError,
    load_verified_release_manifest,
    model_release_record,
)
from quakestrike.infrastructure.settings import Settings


@dataclass(frozen=True, slots=True)
class UnavailableStartupGate:
    """A read-only placeholder until a later phase supplies its adapter."""

    name: str
    reason: str

    def check(self) -> GateResult:
        return GateResult(name=self.name, ready=False, reason=self.reason)


@dataclass(frozen=True, slots=True)
class ModelReleaseStartupGate:
    """Read and compare the selected local bundle with its immutable row."""

    settings: Settings
    name: str = "model-release"

    def check(self) -> GateResult:
        try:
            release = load_verified_release_manifest(
                self.settings.model_artifact_directory,
                SELECTED_RELEASE_MANIFEST_URI,
                require_selected_policy=True,
            )
            if release.release_id != self.settings.model_release_id:
                raise ManifestValidationError(
                    "The configured release ID does not match the manifest."
                )
            engine = create_database_engine(self.settings.database_url)
            try:
                stored = SqlAlchemyModelReleaseRegistry(create_session_factory(engine)).get(
                    release.release_id
                )
            finally:
                engine.dispose()
            expected = model_release_record(release)
            if stored != expected:
                raise ManifestValidationError(
                    "The registered release does not match the verified bundle."
                )
        except (ManifestValidationError, OSError, SQLAlchemyError, ValueError):
            return GateResult(
                name=self.name, ready=False, reason="Model release verification failed."
            )
        return GateResult(name=self.name, ready=True, reason="Model release verified.")


def phase_one_startup_gates(
    settings: Settings,
    *,
    database_gate: StartupGate | None = None,
    redis_gate: StartupGate | None = None,
    migration_gate: StartupGate | None = None,
) -> tuple[StartupGate, ...]:
    """Return the fail-closed gates required by the Phase 1 contract."""

    return (
        migration_gate or AlembicMigrationStateGate(settings),
        ModelReleaseStartupGate(settings),
        UnavailableStartupGate(
            name="bootstrap-readiness",
            reason="Bootstrap readiness is deferred to Phase 8.",
        ),
        database_gate or PostgresConnectivityHealthCheck(settings),
        redis_gate or RedisConnectivityHealthCheck(settings),
    )
