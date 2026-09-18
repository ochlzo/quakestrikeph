from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from quakestrike.application.bootstrap import run_bootstrap
from quakestrike.application.persistence import IngestionRunState
from quakestrike.application.startup import GateResult, StartupReport
from quakestrike.infrastructure.bootstrap import (
    BootstrapSnapshotError,
    default_run_manifest_path,
    evaluate_bootstrap_readiness,
    load_bootstrap_snapshot,
    prepare_run_manifest,
    write_run_manifest,
    write_startup_readiness_manifest,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "bootstrap" / "historical_snapshot.json"
CONFLICTING_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "bootstrap" / "conflicting_revision_snapshot.json"
)
RUN_ID = UUID("00000000-0000-0000-0000-000000000010")
CORRELATION_ID = UUID("00000000-0000-0000-0000-000000000011")


def _state(
    *,
    status: str = "succeeded",
    events_found: int = 8,
    events_inserted: int = 4,
    events_rejected: int = 4,
) -> IngestionRunState:
    return IngestionRunState(
        run_id=RUN_ID,
        trigger_type="backfill",
        status=status,
        correlation_id=CORRELATION_ID,
        attempt_count=1,
        events_found=events_found,
        events_inserted=events_inserted,
        events_revised=0,
        events_unchanged=0,
        events_rejected=events_rejected,
    )


def test_snapshot_loader_counts_rows_and_preserves_bounded_detail_failure() -> None:
    snapshot = load_bootstrap_snapshot(FIXTURE)

    assert snapshot.actual_row_count == 9
    assert len(snapshot.parsed.accepted_rows) == 5
    assert len(snapshot.parsed.rejected_rows) == 4
    assert snapshot.normalized_input_count == 8
    assert snapshot.parsed.accepted_rows[0].origin == "VOLCANIC"
    assert snapshot.parsed.accepted_rows[-1].diagnostics[0].code.value == "DETAIL_FETCH_FAILED"
    assert snapshot.parsed.rejected_rows[-1].diagnostic.code.value == "INVALID_CATALOG_ROW"
    assert all("example.invalid" not in row.source_url for row in snapshot.parsed.accepted_rows)


def test_snapshot_loader_rejects_conflicting_duplicate_revision_before_database_work() -> None:
    with pytest.raises(BootstrapSnapshotError, match="conflicting duplicate"):
        load_bootstrap_snapshot(CONFLICTING_FIXTURE)


def test_snapshot_loader_rejects_embedded_raw_detail_payload(tmp_path: Path) -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["rows"][0]["detail"]["html"] = "<html>not retained</html>"
    path = tmp_path / "raw-payload.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BootstrapSnapshotError, match="Raw HTML"):
        load_bootstrap_snapshot(path)


def test_run_manifest_is_self_consistent_and_atomic(tmp_path: Path) -> None:
    snapshot = load_bootstrap_snapshot(FIXTURE)
    path = tmp_path / "historical.json.bootstrap.json"

    manifest = prepare_run_manifest(snapshot, path)
    loaded = json.loads(path.read_text(encoding="utf-8"))

    assert path == default_run_manifest_path(tmp_path / "historical.json")
    assert loaded == manifest
    assert loaded["snapshot_sha256"] == snapshot.sha256
    assert loaded["counts"]["normalized_inputs"] == 8
    assert loaded["diagnostics"]["INVALID_SOURCE_URL"] == 1
    assert loaded["diagnostics"]["DETAIL_FETCH_FAILED"] == 1

    changed = dict(manifest)
    changed["snapshot_sha256"] = "0" * 64
    write_run_manifest(path, changed)
    with pytest.raises(BootstrapSnapshotError, match="bytes do not match"):
        prepare_run_manifest(snapshot, path)


def test_readiness_requires_successful_run_and_matching_sidecar_counts(tmp_path: Path) -> None:
    snapshot = load_bootstrap_snapshot(FIXTURE)
    manifest = prepare_run_manifest(snapshot, tmp_path / "run.json")
    manifest.update(
        {
            "run_id": str(RUN_ID),
            "correlation_id": str(CORRELATION_ID),
            "status": "succeeded",
        }
    )
    manifest["counts"].update(
        {
            "checkpointed_inputs": 8,
            "events_inserted": 4,
            "events_revised": 0,
            "events_unchanged": 0,
            "events_rejected": 4,
        }
    )

    ready = evaluate_bootstrap_readiness(snapshot, manifest, _state())
    assert ready.ready is True

    incomplete = replace(_state(), status="retry_wait")
    assert evaluate_bootstrap_readiness(snapshot, manifest, incomplete).ready is False
    manifest["counts"]["events_inserted"] = 99
    assert evaluate_bootstrap_readiness(snapshot, manifest, _state()).ready is False


def test_readiness_requires_preserved_source_metadata(tmp_path: Path) -> None:
    snapshot = load_bootstrap_snapshot(FIXTURE)
    manifest = prepare_run_manifest(snapshot, tmp_path / "run.json")
    manifest.update(
        {
            "run_id": str(RUN_ID),
            "correlation_id": str(CORRELATION_ID),
            "status": "succeeded",
        }
    )
    manifest["counts"].update(
        {
            "checkpointed_inputs": 8,
            "events_inserted": 4,
            "events_revised": 0,
            "events_unchanged": 0,
            "events_rejected": 4,
        }
    )

    manifest["source_urls"] = []
    assert evaluate_bootstrap_readiness(snapshot, manifest, _state()).ready is False

    manifest["source_urls"] = list(snapshot.source_urls)
    manifest["retrieved_at"] = "changed"
    assert evaluate_bootstrap_readiness(snapshot, manifest, _state()).ready is False


def test_readiness_requires_persisted_usable_history_and_run_scoped_counts(
    tmp_path: Path,
) -> None:
    snapshot = load_bootstrap_snapshot(FIXTURE)
    manifest = prepare_run_manifest(snapshot, tmp_path / "run.json")
    manifest.update(
        {
            "run_id": str(RUN_ID),
            "correlation_id": str(CORRELATION_ID),
            "status": "succeeded",
        }
    )
    manifest["counts"].update(
        {
            "checkpointed_inputs": 8,
            "events_inserted": 4,
            "events_revised": 0,
            "events_unchanged": 0,
            "events_rejected": 4,
        }
    )

    not_ready = evaluate_bootstrap_readiness(
        snapshot,
        manifest,
        _state(),
        history_observation_count=2,
        usable_history_count=0,
        database_counts={
            "input_checkpoints": 8,
            "event_revisions": 4,
            "prediction_jobs": 1,
            "prediction_dispatches": 1,
        },
    )
    assert not_ready.ready is False
    assert "usable prior observations" in not_ready.reason

    ready = evaluate_bootstrap_readiness(
        snapshot,
        manifest,
        _state(),
        history_observation_count=2,
        usable_history_count=1,
        database_counts={
            "input_checkpoints": 8,
            "event_revisions": 4,
            "prediction_jobs": 1,
            "prediction_dispatches": 1,
        },
    )
    assert ready.ready is True
    assert ready.details["history_observation_count"] == "2"
    assert json.loads(ready.details["database_counts"]) == {
        "event_revisions": 4,
        "input_checkpoints": 8,
        "prediction_dispatches": 1,
        "prediction_jobs": 1,
    }


def test_startup_readiness_manifest_preserves_evidence_and_writes_gate_report(
    tmp_path: Path,
) -> None:
    snapshot = load_bootstrap_snapshot(FIXTURE)
    path = tmp_path / "run.json"
    manifest = prepare_run_manifest(snapshot, path)
    report = StartupReport(
        (
            GateResult(
                name="migration-state",
                ready=True,
                reason="ready",
                details={"current_revision": "head"},
            ),
            GateResult(
                name="model-release",
                ready=True,
                reason="verified",
                details={
                    "release_id": str(UUID(int=1)),
                    "version_label": "SEIS 1.0",
                    "manifest_uri": "seis-1.0/manifest.json",
                    "manifest_hash": "a" * 64,
                    "input_schema_version": "input.v1",
                    "output_schema_version": "output.v1",
                    "artifact_hashes": '{"models/model.bin": "bbbb"}',
                },
            ),
        )
    )

    updated = write_startup_readiness_manifest(
        path,
        report,
        checked_at=datetime(2026, 9, 18, 1, 2, 3, tzinfo=UTC),
    )

    assert updated["snapshot_sha256"] == manifest["snapshot_sha256"]
    assert updated["readiness"]["schema_version"] == "quakestrike.readiness.v1"
    assert updated["readiness"]["checked_at"] == "2026-09-18T01:02:03+00:00"
    assert updated["readiness"]["failed_gate_names"] == []
    assert updated["readiness"]["gates"] == [result.as_dict() for result in report.results]
    assert updated["readiness"]["model_release"] == {
        "release_id": str(UUID(int=1)),
        "version_label": "SEIS 1.0",
        "manifest_uri": "seis-1.0/manifest.json",
        "manifest_hash": "a" * 64,
        "input_schema_version": "input.v1",
        "output_schema_version": "output.v1",
        "artifact_hashes": {"models/model.bin": "bbbb"},
    }


def test_startup_readiness_manifest_replaces_malformed_input_with_minimal_non_ready_report(
    tmp_path: Path,
) -> None:
    path = tmp_path / "run.json"
    path.write_text("not json", encoding="utf-8")
    report = StartupReport(
        (GateResult(name="bootstrap-readiness", ready=False, reason="not ready"),)
    )

    updated = write_startup_readiness_manifest(
        path,
        report,
        checked_at=datetime(2026, 9, 18, tzinfo=UTC),
    )

    assert set(updated) == {"schema_version", "readiness"}
    assert updated["readiness"]["ready"] is False
    assert "snapshot_path" not in updated


def test_bootstrap_can_replace_its_readiness_only_placeholder(tmp_path: Path) -> None:
    snapshot = load_bootstrap_snapshot(FIXTURE)
    path = tmp_path / "run.json"
    write_startup_readiness_manifest(
        path,
        StartupReport((GateResult(name="bootstrap-readiness", ready=False, reason="not ready"),)),
        checked_at=datetime(2026, 9, 18, tzinfo=UTC),
    )

    manifest = prepare_run_manifest(snapshot, path)

    assert manifest["snapshot_sha256"] == snapshot.sha256
    assert "readiness" not in manifest


class _Reconciler:
    def __init__(self, status: str = "succeeded") -> None:
        self.status = status
        self.calls = 0

    def execute(self, _run_id):
        self.calls += 1
        return type("PipelineResult", (), {"status": self.status})()


class _Store:
    def __init__(self, state: IngestionRunState) -> None:
        self.state = state
        self.created: list[tuple[UUID, UUID]] = []

    def create_backfill_run(self, run_id: UUID, correlation_id: UUID) -> IngestionRunState:
        self.created.append((run_id, correlation_id))
        return self.state

    def get_ingestion_run(self, _run_id: UUID) -> IngestionRunState:
        return self.state


def test_run_bootstrap_records_terminal_state_without_reprocessing_succeeded_run() -> None:
    manifest = {"status": "prepared", "counts": {}}
    writes: list[dict[str, object]] = []
    reconciler = _Reconciler()
    result = run_bootstrap(
        store=_Store(_state()),
        reconciler=reconciler,
        run_id=RUN_ID,
        correlation_id=CORRELATION_ID,
        manifest=manifest,
        write_manifest=lambda value: writes.append(dict(value)),
    )

    assert result.reconciliation_status == "already_succeeded"
    assert reconciler.calls == 0
    assert writes[-1]["status"] == "succeeded"


def test_run_bootstrap_starts_and_records_an_active_attempt() -> None:
    pending = replace(
        _state(), status="pending", events_found=0, events_inserted=0, events_rejected=0
    )
    manifest = {"status": "prepared", "counts": {}}
    writes: list[dict[str, object]] = []
    result = run_bootstrap(
        store=_Store(pending),
        reconciler=_Reconciler(),
        run_id=RUN_ID,
        correlation_id=CORRELATION_ID,
        manifest=manifest,
        write_manifest=lambda value: writes.append(dict(value)),
    )

    assert result.reconciliation_status == "succeeded"
    assert writes[0]["status"] == "running"
    assert writes[-1]["reconciliation_status"] == "succeeded"
