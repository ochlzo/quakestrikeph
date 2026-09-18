"""Explicit, resumable bootstrap orchestration over the shared ingestion pipeline."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from quakestrike.application.persistence import IngestionRunState
from quakestrike.application.reconciliation import ReconcileSourceRows


class BootstrapRunStore(Protocol):
    """Persistence operations needed before and after shared reconciliation."""

    def create_backfill_run(self, run_id: UUID, correlation_id: UUID) -> IngestionRunState: ...

    def get_ingestion_run(self, run_id: UUID) -> IngestionRunState | None: ...


class BootstrapTerminalRun(RuntimeError):
    """A durable bootstrap run is terminal and cannot be silently replaced."""


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


def run_bootstrap(
    *,
    store: BootstrapRunStore,
    reconciler: ReconcileSourceRows,
    run_id: UUID,
    correlation_id: UUID,
    manifest: MutableMapping[str, Any],
    write_manifest: Callable[[MutableMapping[str, Any]], None],
) -> BootstrapRunResult:
    """Resume one prepared run without creating an ingestion queue dispatch."""

    state = store.create_backfill_run(run_id, correlation_id)
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
