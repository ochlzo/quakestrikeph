"""Read-only startup gate adapters for worker entry points."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from quakestrike.application.bootstrap import HistoricalBootstrapOperation
from quakestrike.application.model_releases import ModelReleaseVerifier
from quakestrike.application.startup import (
    GateResult,
    ModelReleaseVerificationGate,
    StartupGate,
)
from quakestrike.infrastructure.bootstrap import (
    BootstrapSnapshotError,
    FileBootstrapEvidenceStore,
)
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.database.migration_state import AlembicMigrationStateGate
from quakestrike.infrastructure.database.model_releases import SqlAlchemyModelReleaseRegistry
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.health import (
    PostgresConnectivityHealthCheck,
    RedisConnectivityHealthCheck,
)
from quakestrike.infrastructure.logging.json_logging import configure_logging
from quakestrike.infrastructure.logging.reconciliation import (
    StructuredReconciliationDiagnosticReporter,
)
from quakestrike.infrastructure.models.release_manifest import (
    SELECTED_RELEASE_MANIFEST_URI,
    ManifestValidationError,
    load_verified_release_manifest,
    model_release_record,
)
from quakestrike.infrastructure.phivolcs.client import PhivolcsCatalogClient
from quakestrike.infrastructure.phivolcs.session import create_phivolcs_session
from quakestrike.infrastructure.settings import Settings


@contextmanager
def bootstrap_store(settings: Settings) -> Iterator[SqlAlchemyIngestionTransactions]:
    """Create the bootstrap store and dispose its engine when the operation ends."""

    engine = create_database_engine(settings.database_url)
    try:
        yield SqlAlchemyIngestionTransactions(
            create_session_factory(engine),
            model_release_verifier=ConfiguredModelReleaseVerifier(settings),
        )
    finally:
        engine.dispose()


@contextmanager
def bootstrap_operation(settings: Settings) -> Iterator[HistoricalBootstrapOperation]:
    """Compose the application bootstrap module with its production adapters."""

    session = create_phivolcs_session()
    try:
        with bootstrap_store(settings) as store:
            yield HistoricalBootstrapOperation(
                evidence=FileBootstrapEvidenceStore(
                    settings.bootstrap_run_manifest,
                    required_available_through=(settings.bootstrap_required_available_through),
                ),
                store=store,
                diagnostic_reporter=StructuredReconciliationDiagnosticReporter(
                    configure_logging("bootstrap", level=settings.log_level, stream=sys.stderr)
                ),
                model_release_id=settings.model_release_id,
                detail_enricher=PhivolcsCatalogClient(
                    catalog_url=settings.phivolcs_catalog_url,
                    session=session,
                    max_response_bytes=settings.max_response_bytes,
                    connect_timeout_seconds=settings.http_connect_timeout_seconds,
                    read_timeout_seconds=settings.http_read_timeout_seconds,
                    detail_delay_seconds=settings.detail_request_delay_seconds,
                ),
            )
    finally:
        session.close()


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


@dataclass(frozen=True, slots=True)
class BootstrapReadinessStartupGate:
    """Read the immutable snapshot, sidecar, and durable run without mutating state."""

    settings: Settings
    name: str = "bootstrap-readiness"

    def check(self) -> GateResult:
        try:
            evidence = FileBootstrapEvidenceStore(
                self.settings.bootstrap_run_manifest,
                required_available_through=(self.settings.bootstrap_required_available_through),
            )
            preparation = evidence.load_existing(None)
            with bootstrap_store(self.settings) as store:
                state = store.get_ingestion_run(UUID(str(preparation.manifest["run_id"])))
            readiness = evidence.evaluate_readiness(preparation, state)
            return GateResult(
                name=self.name,
                ready=readiness.ready,
                reason=readiness.reason,
                details=readiness.details,
            )
        except (BootstrapSnapshotError, OSError, SQLAlchemyError, ValueError):
            return GateResult(
                name=self.name,
                ready=False,
                reason="Bootstrap readiness evidence is unavailable or invalid.",
            )


@dataclass(frozen=True, slots=True)
class ConfiguredModelReleaseVerifier(ModelReleaseVerifier):
    """Bind feature work to the configured release and its startup proof."""

    settings: Settings
    startup_gate: ModelReleaseVerificationGate | None = None

    def is_verified(self, release_id: UUID) -> bool:
        if release_id != self.settings.model_release_id:
            return False
        gate = self.startup_gate or ModelReleaseStartupGate(self.settings)
        try:
            return gate.check().ready
        except Exception:
            return False


def phase_one_startup_gates(
    settings: Settings,
    *,
    database_gate: StartupGate | None = None,
    redis_gate: StartupGate | None = None,
    migration_gate: StartupGate | None = None,
    bootstrap_gate: StartupGate | None = None,
) -> tuple[StartupGate, ...]:
    """Return the fail-closed gates required by the Phase 1 contract."""

    return (
        migration_gate or AlembicMigrationStateGate(settings),
        ModelReleaseStartupGate(settings),
        bootstrap_gate or BootstrapReadinessStartupGate(settings),
        database_gate or PostgresConnectivityHealthCheck(settings),
        redis_gate or RedisConnectivityHealthCheck(settings),
    )
