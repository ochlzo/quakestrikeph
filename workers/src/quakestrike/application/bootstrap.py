"""Explicit, resumable bootstrap orchestration over the shared ingestion pipeline."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from quakestrike.application.persistence import IngestionRunState
from quakestrike.application.reconciliation import (
    ReconcileSourceRows,
    ReconciliationDiagnosticReporter,
)
from quakestrike.domain.features import HistoryCoverage
from quakestrike.domain.source_rows import CatalogParseResult, NormalizedSourceRow


class BootstrapRunStore(Protocol):
    """Persistence operations needed before and after shared reconciliation."""

    def create_backfill_run(
        self,
        run_id: UUID,
        correlation_id: UUID,
        snapshot_sha256: str,
        enriched_snapshot_sha256: str | None = None,
    ) -> IngestionRunState: ...

    def requeue_backfill_run(
        self,
        run_id: UUID,
        correlation_id: UUID,
        snapshot_sha256: str,
        enriched_snapshot_sha256: str | None = None,
    ) -> IngestionRunState: ...

    def get_ingestion_run(self, run_id: UUID) -> IngestionRunState | None: ...

    def backfill_run_exists(self) -> bool: ...


class BootstrapCoverage(Protocol):
    def history_coverage(self) -> HistoryCoverage: ...


class BootstrapSnapshot(Protocol):
    path: Path
    sha256: str
    snapshot_kind: str
    parsed: CatalogParseResult
    coverage: BootstrapCoverage

    def with_parsed(self, parsed: CatalogParseResult) -> BootstrapSnapshot: ...


class BootstrapReadiness(Protocol):
    ready: bool

    def as_dict(self) -> dict[str, object]: ...


@dataclass(slots=True)
class BootstrapPreparation:
    snapshot: BootstrapSnapshot
    source_snapshot: BootstrapSnapshot
    manifest_path: Path
    manifest: MutableMapping[str, Any]
    manifest_existed: bool
    enriched_snapshot_sha256: str | None = None

    @property
    def needs_enrichment(self) -> bool:
        return self.source_snapshot.snapshot_kind == "raw" and (
            self.enriched_snapshot_sha256 is None
        )


class BootstrapEvidenceStore(Protocol):
    def prepare_import(
        self,
        snapshot_path: Path,
        requested_manifest_path: Path | None,
    ) -> BootstrapPreparation: ...

    def record_enrichment(
        self,
        preparation: BootstrapPreparation,
        parsed: CatalogParseResult,
    ) -> BootstrapPreparation: ...

    def load_existing(self, requested_manifest_path: Path | None) -> BootstrapPreparation: ...

    def write_manifest(self, preparation: BootstrapPreparation) -> None: ...

    def evaluate_readiness(
        self,
        preparation: BootstrapPreparation,
        run_state: IngestionRunState | None,
    ) -> BootstrapReadiness: ...


class BootstrapDetailEnricher(Protocol):
    def enrich_rows(
        self,
        rows: Sequence[NormalizedSourceRow],
        *,
        heartbeat: Callable[[], bool] | None = None,
    ) -> tuple[NormalizedSourceRow, ...]: ...


class BootstrapTerminalRun(RuntimeError):
    """A durable bootstrap run is terminal and cannot be silently replaced."""


class BootstrapEvidenceConflict(RuntimeError):
    """Local evidence cannot be reconciled with durable bootstrap state."""


@dataclass(frozen=True, slots=True)
class BootstrapRunResult:
    """The run state and shared-pipeline outcome returned to the CLI."""

    state: IngestionRunState
    reconciliation_status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": str(self.state.run_id),
            "correlation_id": str(self.state.correlation_id),
            "status": self.state.status,
            "reconciliation_status": self.reconciliation_status,
            "attempt_count": self.state.attempt_count,
            "counts": {
                "checkpointed_inputs": self.state.events_found,
                "events_inserted": self.state.events_inserted,
                "events_revised": self.state.events_revised,
                "events_unchanged": self.state.events_unchanged,
                "events_rejected": self.state.events_rejected,
            },
            "error_code": self.state.error_code,
        }


@dataclass(frozen=True, slots=True)
class BootstrapCommandResult:
    payload: Mapping[str, object]
    exit_code: int


class HistoricalBootstrapOperation:
    """Run all operator bootstrap actions through one application interface."""

    def __init__(
        self,
        *,
        evidence: BootstrapEvidenceStore,
        store: BootstrapRunStore,
        diagnostic_reporter: ReconciliationDiagnosticReporter,
        model_release_id: UUID,
        detail_enricher: BootstrapDetailEnricher | None = None,
    ) -> None:
        self._evidence = evidence
        self._store = store
        self._diagnostic_reporter = diagnostic_reporter
        self._model_release_id = model_release_id
        self._detail_enricher = detail_enricher

    def execute(
        self,
        snapshot_path: Path,
        requested_manifest_path: Path | None,
    ) -> BootstrapCommandResult:
        preparation = self._evidence.prepare_import(snapshot_path, requested_manifest_path)
        if not preparation.manifest_existed and self._store.backfill_run_exists():
            raise BootstrapEvidenceConflict(
                "The run manifest is missing while a durable backfill run already exists."
            )
        if preparation.needs_enrichment:
            if self._detail_enricher is None:
                raise BootstrapEvidenceConflict("Raw bootstrap evidence requires enrichment.")
            enriched = self._detail_enricher.enrich_rows(
                preparation.source_snapshot.parsed.accepted_rows
            )
            parsed = CatalogParseResult(
                accepted_rows=enriched,
                rejected_rows=preparation.source_snapshot.parsed.rejected_rows,
            )
            preparation = self._evidence.record_enrichment(preparation, parsed)

        reconciler = ReconcileSourceRows(
            store=self._store,
            source_loader=lambda **_: preparation.snapshot.parsed,
            diagnostic_reporter=self._diagnostic_reporter,
            model_release_id=self._model_release_id,
            history_coverage=preparation.snapshot.coverage.history_coverage(),
        )
        result = run_bootstrap(
            store=self._store,
            reconciler=reconciler,
            run_id=_manifest_uuid(preparation.manifest, "run_id"),
            correlation_id=_manifest_uuid(preparation.manifest, "correlation_id"),
            snapshot_sha256=preparation.source_snapshot.sha256,
            enriched_snapshot_sha256=preparation.enriched_snapshot_sha256,
            manifest=preparation.manifest,
            write_manifest=lambda _: self._evidence.write_manifest(preparation),
        )
        readiness = self._evidence.evaluate_readiness(preparation, result.state)
        return BootstrapCommandResult(
            payload={
                "bootstrap": result.as_dict(),
                "readiness": readiness.as_dict(),
                "snapshot_sha256": preparation.source_snapshot.sha256,
            },
            exit_code=0 if result.state.status == "succeeded" and readiness.ready else 2,
        )

    def recover(self, requested_manifest_path: Path | None) -> BootstrapCommandResult:
        preparation = self._evidence.load_existing(requested_manifest_path)
        state = self._store.requeue_backfill_run(
            _manifest_uuid(preparation.manifest, "run_id"),
            _manifest_uuid(preparation.manifest, "correlation_id"),
            preparation.source_snapshot.sha256,
            preparation.enriched_snapshot_sha256,
        )
        preparation.manifest["status"] = state.status
        preparation.manifest["reconciliation_status"] = "requeued"
        preparation.manifest["attempt_count"] = state.attempt_count
        preparation.manifest.pop("error_code", None)
        self._evidence.write_manifest(preparation)
        return BootstrapCommandResult(
            payload={
                "status": "requeued",
                "run_id": str(state.run_id),
                "snapshot_sha256": preparation.source_snapshot.sha256,
            },
            exit_code=0,
        )

    def readiness(self, requested_manifest_path: Path | None) -> BootstrapCommandResult:
        preparation = self._evidence.load_existing(requested_manifest_path)
        state = self._store.get_ingestion_run(_manifest_uuid(preparation.manifest, "run_id"))
        readiness = self._evidence.evaluate_readiness(preparation, state)
        return BootstrapCommandResult(
            payload={
                "readiness": readiness.as_dict(),
                "snapshot_sha256": preparation.source_snapshot.sha256,
                "run_id": preparation.manifest.get("run_id"),
            },
            exit_code=0 if readiness.ready else 2,
        )


def run_bootstrap(
    *,
    store: BootstrapRunStore,
    reconciler: ReconcileSourceRows,
    run_id: UUID,
    correlation_id: UUID,
    snapshot_sha256: str,
    enriched_snapshot_sha256: str | None = None,
    manifest: MutableMapping[str, Any],
    write_manifest: Callable[[MutableMapping[str, Any]], None],
) -> BootstrapRunResult:
    """Resume one prepared run without creating an ingestion queue dispatch."""

    state = store.create_backfill_run(
        run_id,
        correlation_id,
        snapshot_sha256,
        enriched_snapshot_sha256,
    )
    if state.status in {"failed", "cancelled"}:
        _record_manifest_state(manifest, state, "terminal")
        write_manifest(manifest)
        return BootstrapRunResult(state, "terminal")
    if state.status == "succeeded":
        _record_manifest_state(manifest, state, "already_succeeded")
        write_manifest(manifest)
        return BootstrapRunResult(state, "already_succeeded")
    if state.status not in {"pending", "running", "retry_wait"}:
        raise BootstrapTerminalRun(f"Unsupported durable bootstrap state: {state.status}")

    manifest["status"] = "running"
    manifest["reconciliation_status"] = "starting"
    manifest["attempt_count"] = state.attempt_count
    write_manifest(manifest)
    pipeline_result = reconciler.execute(run_id)
    final_state = store.get_ingestion_run(run_id) or state
    _record_manifest_state(manifest, final_state, pipeline_result.status)
    write_manifest(manifest)
    return BootstrapRunResult(final_state, pipeline_result.status)


def _record_manifest_state(
    manifest: MutableMapping[str, Any],
    state: IngestionRunState,
    reconciliation_status: str,
) -> None:
    manifest["status"] = state.status
    manifest["reconciliation_status"] = reconciliation_status
    manifest["attempt_count"] = state.attempt_count
    counts = dict(manifest.get("counts", {}))
    counts.update(
        {
            "checkpointed_inputs": state.events_found,
            "events_inserted": state.events_inserted,
            "events_revised": state.events_revised,
            "events_unchanged": state.events_unchanged,
            "events_rejected": state.events_rejected,
        }
    )
    manifest["counts"] = counts
    if state.error_code is None:
        manifest.pop("error_code", None)
    else:
        manifest["error_code"] = state.error_code


def _manifest_uuid(manifest: Mapping[str, object], key: str) -> UUID:
    return UUID(str(manifest[key]))
