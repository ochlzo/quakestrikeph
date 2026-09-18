from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest

import quakestrike.infrastructure.bootstrap as bootstrap_module
from quakestrike.application.bootstrap import run_bootstrap
from quakestrike.application.persistence import IngestionRunState
from quakestrike.domain.source_rows import CatalogParseResult, SourceTimePrecision
from quakestrike.infrastructure.bootstrap import (
    BootstrapSnapshotError,
    FileBootstrapEvidenceStore,
    default_enriched_snapshot_path,
    ensure_evidence_path_outside_git,
    evaluate_bootstrap_readiness,
    load_bootstrap_snapshot,
    load_enriched_snapshot,
    prepare_run_manifest,
    preserve_bootstrap_snapshot,
    write_enriched_snapshot,
    write_run_manifest,
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
    snapshot_sha256: str | None = None,
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
        snapshot_sha256=snapshot_sha256,
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


def test_enriched_snapshot_requires_a_detail_result_for_each_valid_row(
    tmp_path: Path,
) -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["rows"][0].pop("detail")
    path = tmp_path / "missing-detail-result.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BootstrapSnapshotError, match="completed detail result"):
        load_bootstrap_snapshot(path)


def test_raw_snapshot_ignores_supplied_detail_evidence(tmp_path: Path) -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["snapshot_kind"] = "raw"
    path = tmp_path / "raw-with-detail.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    snapshot = load_bootstrap_snapshot(path)

    assert all(
        row.time_precision is SourceTimePrecision.MINUTE for row in snapshot.parsed.accepted_rows
    )
    assert all(row.origin is None for row in snapshot.parsed.accepted_rows)


def test_enrichment_cache_round_trips_the_normalized_snapshot(tmp_path: Path) -> None:
    snapshot = load_bootstrap_snapshot(FIXTURE)
    cache_path = default_enriched_snapshot_path(snapshot, tmp_path / "run.json")

    cache_hash = write_enriched_snapshot(cache_path, snapshot, snapshot.parsed)
    loaded = load_enriched_snapshot(cache_path, snapshot)

    assert cache_path.is_file()
    assert len(cache_hash) == 64
    assert loaded.parsed == snapshot.parsed


def test_enrichment_cache_cannot_replace_catalog_evidence(tmp_path: Path) -> None:
    snapshot = load_bootstrap_snapshot(FIXTURE)
    cache_path = default_enriched_snapshot_path(snapshot, tmp_path / "run.json")
    write_enriched_snapshot(cache_path, snapshot, snapshot.parsed)
    document = json.loads(cache_path.read_text(encoding="utf-8"))
    document["rows"][0]["magnitude"] = "9.90"
    cache_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BootstrapSnapshotError, match="changed catalog evidence"):
        load_enriched_snapshot(cache_path, snapshot)


def test_new_enrichment_is_validated_before_it_can_be_imported(tmp_path: Path) -> None:
    store = FileBootstrapEvidenceStore(
        tmp_path / "run.json",
        evidence_directory=tmp_path / "evidence",
    )
    preparation = store.prepare_import(FIXTURE, None)
    accepted = list(preparation.source_snapshot.parsed.accepted_rows)
    accepted[0] = replace(accepted[0], source_url=f"{accepted[0].source_url}?changed")
    parsed = CatalogParseResult(
        accepted_rows=tuple(accepted),
        rejected_rows=preparation.source_snapshot.parsed.rejected_rows,
    )

    with pytest.raises(BootstrapSnapshotError, match="changed catalog evidence"):
        store.record_enrichment(preparation, parsed)


def test_snapshot_loader_rejects_conflicting_duplicate_revision_before_database_work() -> None:
    with pytest.raises(BootstrapSnapshotError, match="conflicting duplicate"):
        load_bootstrap_snapshot(CONFLICTING_FIXTURE)


def test_snapshot_loader_rejects_embedded_raw_detail_payload(tmp_path: Path) -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["snapshot_kind"] = "raw"
    document["rows"][0]["detail"]["html"] = "<html>not retained</html>"
    path = tmp_path / "raw-payload.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BootstrapSnapshotError, match="Raw HTML"):
        load_bootstrap_snapshot(path)


def test_snapshot_loader_rejects_incomplete_coverage_before_import(tmp_path: Path) -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["coverage"]["complete"] = False
    path = tmp_path / "incomplete-coverage.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BootstrapSnapshotError, match="coverage is not complete"):
        load_bootstrap_snapshot(path)


def test_snapshot_loader_requires_the_available_september_window(tmp_path: Path) -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["source"]["available_through"] = "2026-09-01T12:00:00+08:00"
    path = tmp_path / "short-september-window.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BootstrapSnapshotError, match="available September window"):
        load_bootstrap_snapshot(path)


def test_snapshot_loader_requires_the_independent_configured_cutoff(tmp_path: Path) -> None:
    del tmp_path
    with pytest.raises(BootstrapSnapshotError, match="configured September cutoff"):
        load_bootstrap_snapshot(
            FIXTURE,
            required_available_through=datetime.fromisoformat("2026-09-02T00:00:00+08:00"),
        )


def test_snapshot_loader_rejects_availability_after_retrieval(tmp_path: Path) -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["source"]["retrieved_at"] = "2026-08-31T23:59:00+08:00"
    path = tmp_path / "impossible-retrieval.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BootstrapSnapshotError, match="cannot be after retrieval"):
        load_bootstrap_snapshot(path)


def test_preserved_snapshot_is_hash_addressed_and_git_ignored(tmp_path: Path) -> None:
    snapshot = load_bootstrap_snapshot(FIXTURE)
    preserved = preserve_bootstrap_snapshot(snapshot, tmp_path / "evidence")

    assert preserved.path.name == f"{snapshot.sha256}.source.json"
    assert preserved.path.read_bytes() == FIXTURE.read_bytes()
    with pytest.raises(BootstrapSnapshotError, match="outside Git"):
        ensure_evidence_path_outside_git(FIXTURE)


def test_preservation_rejects_bytes_that_changed_after_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = load_bootstrap_snapshot(FIXTURE)

    def copy_changed_bytes(_source: Path, destination: Path) -> None:
        destination.write_bytes(b"{}")

    monkeypatch.setattr(bootstrap_module.shutil, "copyfile", copy_changed_bytes)

    with pytest.raises(BootstrapSnapshotError, match="changed while it was being preserved"):
        preserve_bootstrap_snapshot(snapshot, tmp_path / "evidence")


def test_failed_detail_values_cannot_change_catalog_evidence(tmp_path: Path) -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    failed_row = next(
        row for row in document["rows"] if row.get("detail", {}).get("status") == "failed"
    )
    failed_row["detail"]["occurred_at"] = "2026-08-31T12:00:45+08:00"
    failed_row["detail"]["origin"] = "TECTONIC"
    path = tmp_path / "failed-detail-values.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    snapshot = load_bootstrap_snapshot(path)
    row = next(
        item
        for item in snapshot.parsed.accepted_rows
        if item.source_bulletin_id == failed_row["catalog"]["source_bulletin_id"]
    )

    assert row.time_precision is SourceTimePrecision.MINUTE
    assert row.origin is None


def test_existing_manifest_rejects_a_different_supplied_raw_snapshot(
    tmp_path: Path,
) -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["snapshot_kind"] = "raw"
    first_path = tmp_path / "first.json"
    first_path.write_text(json.dumps(document), encoding="utf-8")
    store = FileBootstrapEvidenceStore(
        tmp_path / "run.json",
        evidence_directory=tmp_path / "evidence",
    )
    store.prepare_import(first_path, None)

    document["source"]["retrieved_at"] = "2026-09-18T09:01:00+08:00"
    second_path = tmp_path / "second.json"
    second_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BootstrapSnapshotError, match="supplied source snapshot"):
        store.prepare_import(second_path, None)


def test_snapshot_loader_counts_missing_source_identity_without_inference(tmp_path: Path) -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["rows"][0]["catalog"].pop("source_bulletin_id")
    document["rows"][0]["catalog"].pop("source_event_group_id")
    path = tmp_path / "missing-identity.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    snapshot = load_bootstrap_snapshot(path)

    assert any(
        rejected.diagnostic.code.value == "INVALID_CATALOG_ROW"
        for rejected in snapshot.parsed.rejected_rows
    )


def test_snapshot_loader_rejects_bulletin_id_not_supported_by_group_only_url(
    tmp_path: Path,
) -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["rows"][0]["catalog"]["source_url"] = document["rows"][0]["catalog"][
        "source_url"
    ].replace("_B1.html", ".html")
    path = tmp_path / "conflicting-url-identity.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    snapshot = load_bootstrap_snapshot(path)

    assert any(
        rejected.diagnostic.code.value == "INVALID_CATALOG_ROW"
        for rejected in snapshot.parsed.rejected_rows
    )


def test_run_manifest_is_self_consistent_and_atomic(tmp_path: Path) -> None:
    snapshot = load_bootstrap_snapshot(FIXTURE)
    path = tmp_path / "historical.json.bootstrap.json"

    manifest = prepare_run_manifest(snapshot, path)
    loaded = json.loads(path.read_text(encoding="utf-8"))

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

    ready = evaluate_bootstrap_readiness(
        snapshot, manifest, _state(snapshot_sha256=snapshot.sha256)
    )
    assert ready.ready is True

    incomplete = replace(_state(), status="retry_wait")
    assert evaluate_bootstrap_readiness(snapshot, manifest, incomplete).ready is False
    manifest["counts"]["events_inserted"] = 99
    assert (
        evaluate_bootstrap_readiness(
            snapshot, manifest, _state(snapshot_sha256=snapshot.sha256)
        ).ready
        is False
    )


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

    def create_backfill_run(
        self,
        run_id: UUID,
        correlation_id: UUID,
        _snapshot_sha256: str,
        _enriched_snapshot_sha256: str | None = None,
    ) -> IngestionRunState:
        self.created.append((run_id, correlation_id))
        return self.state

    def requeue_backfill_run(
        self,
        run_id,
        correlation_id,
        snapshot_sha256,
        enriched_snapshot_sha256=None,
    ):
        raise AssertionError("not used in this test")

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
        snapshot_sha256="0" * 64,
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
        snapshot_sha256="0" * 64,
        manifest=manifest,
        write_manifest=lambda value: writes.append(dict(value)),
    )

    assert result.reconciliation_status == "succeeded"
    assert writes[0]["status"] == "running"
    assert writes[-1]["reconciliation_status"] == "succeeded"
