"""Verify bootstrap recovery and commit its audit before publishing evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from quakestrike.application.bootstrap import BootstrapSnapshot
from quakestrike.application.features import HistorySelection
from quakestrike.application.persistence import IngestionRunState
from quakestrike.domain.features import HistoryCoverage, select_usable_history

AUDIT_ACTION = "bootstrap_readiness_recovery_verified"


class UnsafeBootstrapRecovery(ValueError):
    """The preserved run, file, or audit cannot establish recovery readiness."""


@dataclass(frozen=True, slots=True)
class BootstrapRecoveryAudit:
    audit_id: UUID
    action: str
    target_id: str
    outcome: str
    correlation_id: UUID
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class BootstrapRecoveryCounts:
    database: Mapping[str, int]
    history_observations: int
    usable_history: int


class BootstrapRecoveryTransaction(Protocol):
    def completed_runs(self, run_id: UUID | None) -> tuple[IngestionRunState, ...]: ...

    def database_counts(self, run_id: UUID) -> Mapping[str, int]: ...

    def history(self, anchor: datetime, coverage: HistoryCoverage) -> HistorySelection: ...

    def audit(self, audit_id: UUID) -> BootstrapRecoveryAudit | None: ...

    def record_audit(self, audit: BootstrapRecoveryAudit) -> None: ...


class BootstrapRecoveryStore(Protocol):
    def transaction(self) -> AbstractContextManager[BootstrapRecoveryTransaction]: ...


class BootstrapRecoveryEvidence(Protocol):
    def source_path(self, target: Path, sha256: str | None) -> Path | None: ...

    def load_source(self, path: Path) -> BootstrapSnapshot: ...

    def load_enriched(
        self, path: Path, source: BootstrapSnapshot, sha256: str
    ) -> BootstrapSnapshot: ...

    def new_manifest(self, snapshot: BootstrapSnapshot) -> dict[str, Any]: ...

    def load_manifest(self, path: Path) -> dict[str, Any] | None: ...

    def readiness_error(
        self,
        snapshot: BootstrapSnapshot,
        manifest: Mapping[str, Any],
        state: IngestionRunState,
        counts: BootstrapRecoveryCounts,
    ) -> str | None: ...

    def publish(self, path: Path, payload: bytes) -> None: ...


class RecoverBootstrapReadiness:
    def __init__(self, store: BootstrapRecoveryStore, evidence: BootstrapRecoveryEvidence):
        self._store = store
        self._evidence = evidence

    def run(
        self,
        *,
        apply: bool,
        snapshot_path: Path | None,
        enriched_snapshot_path: Path | None,
        manifest_path: Path,
        run_id: UUID | None,
    ) -> dict[str, object]:
        target = manifest_path
        with self._store.transaction() as transaction:
            runs = transaction.completed_runs(run_id)
            source = self._evidence.load_source(snapshot_path) if snapshot_path else None
            candidates = [
                state
                for state in runs
                if (
                    state.snapshot_sha256 == source.sha256
                    if source is not None
                    else self._evidence.source_path(target, state.snapshot_sha256) is not None
                )
            ]
            if len(candidates) != 1:
                raise UnsafeBootstrapRecovery(
                    "Expected one completed run; specify --run-id and --snapshot if ambiguous."
                )
            state = candidates[0]
            if source is None:
                preserved = self._evidence.source_path(target, state.snapshot_sha256)
                if preserved is None:
                    raise UnsafeBootstrapRecovery("The preserved source snapshot is unavailable.")
                source = self._evidence.load_source(preserved)
            if source.sha256 != state.snapshot_sha256:
                raise UnsafeBootstrapRecovery(
                    "The source snapshot does not match the recorded hash."
                )
            snapshot = source
            if state.enriched_snapshot_sha256 is not None:
                if enriched_snapshot_path is None:
                    raise UnsafeBootstrapRecovery("The bound enrichment cache is required.")
                snapshot = self._evidence.load_enriched(
                    enriched_snapshot_path, source, state.enriched_snapshot_sha256
                )
            elif source.snapshot_kind == "raw":
                raise UnsafeBootstrapRecovery("Raw evidence has no bound enrichment cache.")

            manifest = self._evidence.new_manifest(snapshot)
            manifest.update(
                run_id=str(state.run_id),
                correlation_id=str(state.correlation_id),
                status=state.status,
                attempt_count=state.attempt_count,
                reconciliation_status="reconstructed",
            )
            manifest["counts"].update(
                checkpointed_inputs=state.events_found,
                events_inserted=state.events_inserted,
                events_revised=state.events_revised,
                events_unchanged=state.events_unchanged,
                events_rejected=state.events_rejected,
            )
            if state.enriched_snapshot_sha256 is not None:
                manifest["enriched_snapshot_path"] = str(enriched_snapshot_path.resolve())
                manifest["enriched_snapshot_sha256"] = state.enriched_snapshot_sha256
            history = transaction.history(
                snapshot.coverage.first_prediction_anchor, snapshot.coverage.history_coverage()
            )
            usable = select_usable_history(
                snapshot.coverage.first_prediction_anchor,
                history.observations,
                anchor_time_precision="minute",
            )
            counts = BootstrapRecoveryCounts(
                transaction.database_counts(state.run_id), len(history.observations), len(usable)
            )
            error = self._evidence.readiness_error(snapshot, manifest, state, counts)
            if error is not None:
                raise UnsafeBootstrapRecovery(error)
            audit_id = uuid5(
                NAMESPACE_URL,
                f"quakestrike-bootstrap-recovery:{state.run_id}:{source.sha256}:{target}",
            )
            manifest["recovery"] = {"kind": "reconstructed", "audit_id": str(audit_id)}
            payload = (
                json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
            ).encode()
            expected = BootstrapRecoveryAudit(
                audit_id=audit_id,
                action=AUDIT_ACTION,
                target_id=str(state.run_id),
                outcome="succeeded",
                correlation_id=state.correlation_id,
                metadata={
                    "snapshot_sha256": source.sha256,
                    "manifest_sha256": hashlib.sha256(payload).hexdigest(),
                    "manifest_path": str(target),
                    "checkpoint_count": counts.database["input_checkpoints"],
                    "event_revisions": counts.database["event_revisions"],
                    "usable_history_count": counts.usable_history,
                },
            )
            existing = transaction.audit(audit_id)
            if existing is not None and existing != expected:
                raise UnsafeBootstrapRecovery("The existing recovery audit record conflicts.")
            saved = self._evidence.load_manifest(target)
            report = {"action": "recover-bootstrap-readiness", "run_id": str(state.run_id)}
            if saved is not None:
                saved.pop("readiness", None)
                if saved != manifest:
                    if (
                        saved.get("run_id") == str(state.run_id)
                        and saved.get("correlation_id") == str(state.correlation_id)
                        and saved.get("snapshot_sha256") == source.sha256
                        and not saved.get("recovery")
                        and self._evidence.readiness_error(snapshot, saved, state, counts) is None
                    ):
                        return {**report, "status": "existing_file_matches"}
                    raise UnsafeBootstrapRecovery(
                        "The readiness file already exists and will not be replaced."
                    )
                if existing is None:
                    raise UnsafeBootstrapRecovery(
                        "The existing recovery file has no matching audit record."
                    )
                return {**report, "status": "already_recovered", "audit_id": str(audit_id)}
            if not apply:
                return {
                    **report,
                    "status": "ready_to_apply",
                    "snapshot_sha256": source.sha256,
                    "checkpoint_count": counts.database["input_checkpoints"],
                    "event_revisions": counts.database["event_revisions"],
                    "usable_history_count": counts.usable_history,
                    "manifest_path": str(target),
                }
            if existing is None:
                transaction.record_audit(expected)
        # Publication starts only after the evidence audit commits successfully.
        self._evidence.publish(target, payload)
        return {
            **report,
            "status": "recovered",
            "audit_id": str(audit_id),
            "manifest_path": str(target),
        }
