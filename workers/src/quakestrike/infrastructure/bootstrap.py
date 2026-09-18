"""Bootstrap snapshot validation and ignored operator evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from quakestrike.application.bootstrap import BootstrapPreparation
from quakestrike.application.startup import StartupReport
from quakestrike.domain.features import HistoryCoverage, evaluate_history_readiness
from quakestrike.domain.source_rows import (
    CatalogParseResult,
    DiagnosticCode,
    NormalizedSourceRow,
    RejectedSourceRow,
    SourceDiagnostic,
    SourceTimePrecision,
)
from quakestrike.infrastructure.phivolcs.parser import normalize_detail_origin
from quakestrike.infrastructure.phivolcs.urls import (
    OFFICIAL_HOST,
    BulletinUrlRejected,
    canonicalize_bulletin_url,
)

SNAPSHOT_SCHEMA_VERSION = "quakestrike.bootstrap-snapshot.v1"
RUN_MANIFEST_SCHEMA_VERSION = "quakestrike.bootstrap-run.v1"
ENRICHED_CACHE_SCHEMA_VERSION = "quakestrike.bootstrap-enriched.v1"
DEFAULT_BOOTSTRAP_EVIDENCE_DIRECTORY = Path("bootstrap-snapshots/source-snapshots")
READINESS_SCHEMA_VERSION = "quakestrike.readiness.v1"
MANILA = ZoneInfo("Asia/Manila")
_MINIMUM_LOOKBACK_START = datetime(2026, 8, 25, tzinfo=MANILA)
_ALLOWED_DETAIL_STATUSES = {"enriched", "failed", "not_attempted"}
_DETAIL_FAILURE_CODES = {
    DiagnosticCode.DETAIL_FETCH_FAILED,
    DiagnosticCode.DETAIL_NON_HTML_RESPONSE,
    DiagnosticCode.DETAIL_DECODE_FAILED,
    DiagnosticCode.DETAIL_TIMESTAMP_MISSING,
}
_FORBIDDEN_EMBEDDED_PAYLOAD_KEYS = frozenset(
    {"body", "exception", "exception_text", "error", "error_text", "html", "raw_html", "raw_href"}
)


class BootstrapSnapshotError(ValueError):
    """The preserved source snapshot cannot be safely imported."""


@dataclass(frozen=True, slots=True)
class SnapshotCoverage:
    """Declared source coverage and the first intended prediction anchor."""

    start: datetime
    end: datetime
    complete: bool
    first_prediction_anchor: datetime

    def history_coverage(self) -> HistoryCoverage:
        return HistoryCoverage(self.start, self.end, self.complete)


@dataclass(frozen=True, slots=True)
class BootstrapSnapshot:
    """Validated metadata and normalized rows from one preserved snapshot."""

    path: Path
    sha256: str
    snapshot_kind: str
    source_urls: tuple[str, ...]
    retrieved_at: datetime
    available_through: datetime
    coverage: SnapshotCoverage
    declared_row_count: int
    parsed: CatalogParseResult

    def with_parsed(self, parsed: CatalogParseResult) -> BootstrapSnapshot:
        return replace(self, parsed=parsed)

    @property
    def actual_row_count(self) -> int:
        return len(self.parsed.accepted_rows) + len(self.parsed.rejected_rows)

    @property
    def actual_coverage_start(self) -> datetime | None:
        if not self.parsed.accepted_rows:
            return None
        return min(row.occurred_at for row in self.parsed.accepted_rows)

    @property
    def actual_coverage_end(self) -> datetime | None:
        if not self.parsed.accepted_rows:
            return None
        return max(row.occurred_at for row in self.parsed.accepted_rows)

    @property
    def normalized_input_count(self) -> int:
        """Return the number of durable input checkpoints the shared pipeline needs."""

        from quakestrike.application.reconciliation import coalesce_catalog_rows

        return len(coalesce_catalog_rows(self.parsed)) + len(self.parsed.rejected_rows)

    @property
    def diagnostic_counts(self) -> dict[str, int]:
        """Return only stable diagnostic codes for the external evidence sidecar."""

        counts: Counter[str] = Counter()
        for row in self.parsed.accepted_rows:
            counts.update(diagnostic.code.value for diagnostic in row.diagnostics)
        counts.update(rejected.diagnostic.code.value for rejected in self.parsed.rejected_rows)
        return dict(sorted(counts.items()))


@dataclass(frozen=True, slots=True)
class BootstrapReadiness:
    """Read-only result used by the bootstrap CLI and startup gate."""

    ready: bool
    reason: str
    details: Mapping[str, str]

    def as_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "reason": self.reason,
            "details": dict(self.details),
        }


def evaluate_bootstrap_readiness(
    snapshot: BootstrapSnapshot,
    manifest: Mapping[str, Any],
    run_state: object | None,
    *,
    history_observation_count: int | None = None,
    usable_history_count: int | None = None,
    database_counts: Mapping[str, int] | None = None,
) -> BootstrapReadiness:
    """Prove that one completed sidecar and its database run are safe to start from."""

    if manifest.get("snapshot_sha256") != snapshot.sha256:
        return _not_ready("The run manifest hash does not match the snapshot.")
    if Path(str(manifest.get("snapshot_path", ""))).resolve() != snapshot.path:
        return _not_ready("The run manifest path does not match the snapshot.")
    evidence_error = _snapshot_manifest_evidence_error(snapshot, manifest)
    if evidence_error is not None:
        return _not_ready(evidence_error)
    if run_state is None:
        return _not_ready("The durable bootstrap run does not exist.")
    if getattr(run_state, "trigger_type", None) != "backfill":
        return _not_ready("The durable run is not a backfill run.")
    if getattr(run_state, "status", None) != "succeeded":
        return _not_ready("The durable bootstrap run has not succeeded.")
    if manifest.get("status") != "succeeded":
        return _not_ready("The run manifest has not recorded a successful run.")
    if getattr(run_state, "snapshot_sha256", None) != snapshot.sha256:
        return _not_ready("The durable backfill run is not bound to this snapshot.")
    if str(getattr(run_state, "run_id", "")) != str(manifest.get("run_id", "")):
        return _not_ready("The run manifest and durable run IDs do not match.")
    if str(getattr(run_state, "correlation_id", "")) != str(manifest.get("correlation_id", "")):
        return _not_ready("The run manifest and durable correlation IDs do not match.")

    counts = manifest["counts"]
    expected_run_counts = {
        "checkpointed_inputs": getattr(run_state, "events_found", None),
        "events_inserted": getattr(run_state, "events_inserted", None),
        "events_revised": getattr(run_state, "events_revised", None),
        "events_unchanged": getattr(run_state, "events_unchanged", None),
        "events_rejected": getattr(run_state, "events_rejected", None),
    }
    for key, expected in expected_run_counts.items():
        if counts.get(key) != expected:
            return _not_ready(f"The run manifest {key} count is inconsistent.")
    if getattr(run_state, "events_found", None) != snapshot.normalized_input_count:
        return _not_ready("The durable checkpoint count does not cover the snapshot inputs.")

    coverage = snapshot.coverage
    if not coverage.complete:
        return _not_ready("The snapshot coverage is not complete.")
    if coverage.start.astimezone(UTC) > _MINIMUM_LOOKBACK_START.astimezone(UTC):
        return _not_ready("The snapshot starts after the required August lookback.")
    history = evaluate_history_readiness(
        coverage.first_prediction_anchor,
        coverage.history_coverage(),
    )
    if not history.ready:
        return _not_ready(history.reason or "The snapshot history coverage is not ready.")
    if snapshot.actual_coverage_start is None or snapshot.actual_coverage_end is None:
        return _not_ready("The snapshot contains no accepted source rows.")
    if snapshot.actual_coverage_start.astimezone(UTC) > _MINIMUM_LOOKBACK_START.astimezone(UTC):
        return _not_ready("Accepted source rows do not reach the required August lookback.")
    if snapshot.actual_coverage_end.astimezone(UTC) < coverage.first_prediction_anchor.astimezone(
        UTC
    ):
        return _not_ready("Accepted source rows do not reach the first prediction anchor.")

    if history_observation_count is not None or usable_history_count is not None:
        if history_observation_count is None or usable_history_count is None:
            return _not_ready("Persisted history evidence is incomplete.")
        if usable_history_count <= 0:
            return _not_ready(
                "The database contains no usable prior observations for the first anchor."
            )

    if database_counts is not None:
        expected_database_counts = {
            "input_checkpoints": run_state.events_found,
            "event_revisions": run_state.events_inserted + run_state.events_revised,
        }
        for key, expected in expected_database_counts.items():
            if database_counts.get(key) != expected:
                return _not_ready(f"The database {key} count is inconsistent with the run.")

    details = {
        "run_id": str(run_state.run_id),
        "snapshot_sha256": snapshot.sha256,
        "checkpointed_inputs": str(run_state.events_found),
    }
    if history_observation_count is not None and usable_history_count is not None:
        details.update(
            {
                "history_anchor": coverage.first_prediction_anchor.isoformat(),
                "history_coverage_start": coverage.start.isoformat(),
                "history_coverage_end": coverage.end.isoformat(),
                "history_coverage_complete": str(coverage.complete).lower(),
                "history_observation_count": str(history_observation_count),
                "usable_history_count": str(usable_history_count),
                "history_required_start": history.required_start.isoformat(),
                "history_required_end": history.required_end.isoformat(),
            }
        )
    if database_counts is not None:
        details["database_counts"] = json.dumps(dict(database_counts), sort_keys=True)
    return BootstrapReadiness(
        ready=True,
        reason="Bootstrap snapshot, durable run, and history coverage are ready.",
        details=details,
    )


def _not_ready(reason: str) -> BootstrapReadiness:
    return BootstrapReadiness(ready=False, reason=reason, details={})


def _snapshot_manifest_evidence_error(
    snapshot: BootstrapSnapshot,
    manifest: Mapping[str, Any],
) -> str | None:
    expected = {
        "snapshot_kind": snapshot.snapshot_kind,
        "alert_policy": "suppressed",
        "declared_row_count": snapshot.declared_row_count,
        "source_urls": list(snapshot.source_urls),
        "retrieved_at": snapshot.retrieved_at.isoformat(),
        "available_through": snapshot.available_through.isoformat(),
        "coverage": _coverage_document(snapshot.coverage),
        "diagnostics": snapshot.diagnostic_counts,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        return "The run manifest evidence does not match the snapshot."
    counts = manifest.get("counts")
    if not isinstance(counts, Mapping):
        return "The run manifest does not contain durable counts."
    expected_counts = {
        "snapshot_rows": snapshot.actual_row_count,
        "accepted_rows": len(snapshot.parsed.accepted_rows),
        "rejected_rows": len(snapshot.parsed.rejected_rows),
        "normalized_inputs": snapshot.normalized_input_count,
    }
    for key, value in expected_counts.items():
        if counts.get(key) != value:
            return f"The run manifest {key} count is inconsistent."
    return None


def load_bootstrap_snapshot(
    path: Path,
    *,
    required_available_through: datetime | None = None,
) -> BootstrapSnapshot:
    """Hash exact bytes, validate the envelope, and normalize every row."""

    try:
        raw = path.resolve().read_bytes()
    except OSError as error:
        raise BootstrapSnapshotError("The bootstrap snapshot could not be read.") from error
    digest = hashlib.sha256(raw).hexdigest()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BootstrapSnapshotError("The bootstrap snapshot is not valid UTF-8 JSON.") from error
    if not isinstance(document, Mapping):
        raise BootstrapSnapshotError("The bootstrap snapshot envelope must be an object.")
    if document.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise BootstrapSnapshotError("The bootstrap snapshot schema version is unsupported.")

    snapshot_kind = _required_text(document, "snapshot_kind")
    if snapshot_kind not in {"raw", "enriched"}:
        raise BootstrapSnapshotError("snapshot_kind must be raw or enriched.")
    source = _required_mapping(document, "source")
    if _required_text(source, "provider").upper() != "PHIVOLCS":
        raise BootstrapSnapshotError("The bootstrap source provider must be PHIVOLCS.")
    source_urls = _source_urls(source.get("catalog_urls"))
    retrieved_at = _aware_datetime(source.get("retrieved_at"), "source.retrieved_at")
    available_through = _aware_datetime(
        source.get("available_through"),
        "source.available_through",
    )

    coverage_document = _required_mapping(document, "coverage")
    coverage = SnapshotCoverage(
        start=_aware_datetime(coverage_document.get("start"), "coverage.start"),
        end=_aware_datetime(coverage_document.get("end"), "coverage.end"),
        complete=_required_bool(coverage_document, "complete"),
        first_prediction_anchor=_aware_datetime(
            coverage_document.get("first_prediction_anchor"),
            "coverage.first_prediction_anchor",
        ),
    )
    _validate_coverage(
        coverage,
        retrieved_at,
        available_through,
        required_available_through,
    )

    declared_row_count = document.get("declared_row_count")
    if not isinstance(declared_row_count, int) or isinstance(declared_row_count, bool):
        raise BootstrapSnapshotError("declared_row_count must be a nonnegative integer.")
    if declared_row_count < 0:
        raise BootstrapSnapshotError("declared_row_count must be a nonnegative integer.")
    rows = document.get("rows")
    if not isinstance(rows, list):
        raise BootstrapSnapshotError("rows must be an array.")
    if declared_row_count != len(rows):
        raise BootstrapSnapshotError("declared_row_count does not match rows.")

    accepted: list[NormalizedSourceRow] = []
    rejected: list[RejectedSourceRow] = []
    seen_row_numbers: set[int] = set()
    for index, value in enumerate(rows, start=1):
        row_number = _row_number(value, index)
        if row_number in seen_row_numbers:
            raise BootstrapSnapshotError("Snapshot row numbers must be unique.")
        seen_row_numbers.add(row_number)
        try:
            accepted.append(
                _load_snapshot_row(
                    value,
                    row_number,
                    snapshot_kind=snapshot_kind,
                )
            )
        except _RejectedSnapshotRow as error:
            rejected.append(RejectedSourceRow(row_number, error.diagnostic))

    accepted.sort(key=lambda row: (row.occurred_at, row.source_bulletin_id or ""))
    _validate_rows_against_coverage(accepted, coverage)
    try:
        from quakestrike.application.reconciliation import coalesce_catalog_rows

        coalesce_catalog_rows(CatalogParseResult(tuple(accepted), ()))
    except ValueError as error:
        raise BootstrapSnapshotError(
            "The bootstrap snapshot contains conflicting duplicate bulletin values."
        ) from error
    _validate_import_coverage(accepted, coverage, available_through)
    return BootstrapSnapshot(
        path=path.resolve(),
        sha256=digest,
        snapshot_kind=snapshot_kind,
        source_urls=source_urls,
        retrieved_at=retrieved_at,
        available_through=available_through,
        coverage=coverage,
        declared_row_count=declared_row_count,
        parsed=CatalogParseResult(tuple(accepted), tuple(rejected)),
    )


class FileBootstrapEvidenceStore:
    """Keep source snapshots, enrichment caches, and the run sidecar consistent."""

    def __init__(
        self,
        default_manifest_path: Path,
        *,
        required_available_through: datetime | None = None,
        evidence_directory: Path = DEFAULT_BOOTSTRAP_EVIDENCE_DIRECTORY,
    ) -> None:
        self._default_manifest_path = default_manifest_path
        self._required_available_through = required_available_through
        self._evidence_directory = evidence_directory

    def prepare_import(
        self,
        snapshot_path: Path,
        requested_manifest_path: Path | None,
    ) -> BootstrapPreparation:
        source_snapshot = preserve_bootstrap_snapshot(
            load_bootstrap_snapshot(
                snapshot_path,
                required_available_through=self._required_available_through,
            ),
            self._evidence_directory,
        )
        manifest_path = (requested_manifest_path or self._default_manifest_path).resolve()
        ensure_evidence_path_outside_git(manifest_path)
        manifest_existed = manifest_path.exists()
        snapshot = source_snapshot
        enriched_snapshot_sha256 = None
        enriched_snapshot_path = None
        if source_snapshot.snapshot_kind == "raw" and manifest_existed:
            existing_manifest = load_run_manifest(manifest_path)
            if (
                existing_manifest.get("snapshot_sha256") != source_snapshot.sha256
                or Path(str(existing_manifest.get("snapshot_path", ""))).resolve()
                != source_snapshot.path
            ):
                raise BootstrapSnapshotError(
                    "The supplied source snapshot does not match the existing run manifest."
                )
            if existing_manifest.get("enriched_snapshot_path"):
                snapshot = load_snapshot_for_manifest(
                    existing_manifest,
                    required_available_through=self._required_available_through,
                )
                enriched_snapshot_path = Path(
                    str(existing_manifest["enriched_snapshot_path"])
                ).resolve()
                enriched_snapshot_sha256 = str(existing_manifest["enriched_snapshot_sha256"])
        manifest = prepare_run_manifest(
            snapshot,
            manifest_path,
            enriched_snapshot_path=enriched_snapshot_path,
            enriched_snapshot_sha256=enriched_snapshot_sha256,
        )
        return BootstrapPreparation(
            snapshot=snapshot,
            source_snapshot=source_snapshot,
            manifest_path=manifest_path,
            manifest=manifest,
            manifest_existed=manifest_existed,
            enriched_snapshot_sha256=enriched_snapshot_sha256,
        )

    def record_enrichment(
        self,
        preparation: BootstrapPreparation,
        parsed: CatalogParseResult,
    ) -> BootstrapPreparation:
        _validate_enriched_cache(
            preparation.source_snapshot,
            parsed.accepted_rows,
            parsed.rejected_rows,
        )
        cache_path = default_enriched_snapshot_path(
            preparation.source_snapshot,
            preparation.manifest_path,
        )
        snapshot = preparation.source_snapshot.with_parsed(parsed)
        cache_hash = write_enriched_snapshot(
            cache_path,
            preparation.source_snapshot,
            parsed,
        )
        preparation.manifest["enriched_snapshot_path"] = str(cache_path.resolve())
        preparation.manifest["enriched_snapshot_sha256"] = cache_hash
        preparation.manifest["diagnostics"] = snapshot.diagnostic_counts
        updated = BootstrapPreparation(
            snapshot=snapshot,
            source_snapshot=preparation.source_snapshot,
            manifest_path=preparation.manifest_path,
            manifest=preparation.manifest,
            manifest_existed=preparation.manifest_existed,
            enriched_snapshot_sha256=cache_hash,
        )
        self.write_manifest(updated)
        return updated

    def load_existing(self, requested_manifest_path: Path | None) -> BootstrapPreparation:
        manifest_path = (requested_manifest_path or self._default_manifest_path).resolve()
        ensure_evidence_path_outside_git(manifest_path)
        manifest = load_run_manifest(manifest_path)
        source_snapshot = load_bootstrap_snapshot(
            Path(str(manifest["snapshot_path"])),
            required_available_through=self._required_available_through,
        )
        snapshot = load_snapshot_for_manifest(
            manifest,
            required_available_through=self._required_available_through,
        )
        cache_path = manifest.get("enriched_snapshot_path")
        manifest = prepare_run_manifest(
            snapshot,
            manifest_path,
            enriched_snapshot_path=Path(str(cache_path)) if cache_path else None,
            enriched_snapshot_sha256=(
                str(manifest["enriched_snapshot_sha256"]) if cache_path else None
            ),
        )
        return BootstrapPreparation(
            snapshot=snapshot,
            source_snapshot=source_snapshot,
            manifest_path=manifest_path,
            manifest=manifest,
            manifest_existed=True,
            enriched_snapshot_sha256=(
                str(manifest["enriched_snapshot_sha256"]) if cache_path else None
            ),
        )

    def write_manifest(self, preparation: BootstrapPreparation) -> None:
        write_run_manifest(preparation.manifest_path, preparation.manifest)

    def evaluate_readiness(
        self,
        preparation: BootstrapPreparation,
        run_state: object | None,
        *,
        history_observation_count: int | None = None,
        usable_history_count: int | None = None,
        database_counts: Mapping[str, int] | None = None,
    ) -> BootstrapReadiness:
        readiness = evaluate_bootstrap_readiness(
            preparation.snapshot,
            preparation.manifest,
            run_state,
            history_observation_count=history_observation_count,
            usable_history_count=usable_history_count,
            database_counts=database_counts,
        )
        expected_enriched_hash = preparation.enriched_snapshot_sha256
        if (
            readiness.ready
            and getattr(run_state, "enriched_snapshot_sha256", None) != expected_enriched_hash
        ):
            return _not_ready("The durable backfill run is not bound to its enrichment cache.")
        return readiness


def preserve_bootstrap_snapshot(
    snapshot: BootstrapSnapshot,
    evidence_directory: Path = DEFAULT_BOOTSTRAP_EVIDENCE_DIRECTORY,
) -> BootstrapSnapshot:
    """Copy exact source bytes into the ignored, hash-addressed evidence store."""

    destination = (evidence_directory / f"{snapshot.sha256}.source.json").resolve()
    ensure_evidence_path_outside_git(destination)
    if destination == snapshot.path:
        return snapshot
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != snapshot.sha256:
            raise BootstrapSnapshotError("Preserved snapshot evidence does not match its hash.")
    else:
        temporary = destination.with_suffix(f"{destination.suffix}.{uuid4().hex}.tmp")
        try:
            shutil.copyfile(snapshot.path, temporary)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != snapshot.sha256:
                raise BootstrapSnapshotError(
                    "The source snapshot changed while it was being preserved."
                )
            os.replace(temporary, destination)
        except OSError as error:
            raise BootstrapSnapshotError(
                "The bootstrap snapshot could not be preserved."
            ) from error
        finally:
            if temporary.exists():
                temporary.unlink()
    return replace(snapshot, path=destination)


def ensure_evidence_path_outside_git(path: Path) -> None:
    """Reject repository-local evidence paths unless Git ignores them."""

    git = shutil.which("git")
    if git is None:
        return
    probe = subprocess.run(
        [git, "rev-parse", "--show-toplevel"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return
    root = Path(probe.stdout.strip()).resolve()
    try:
        relative = path.resolve().relative_to(root)
    except ValueError:
        return
    tracked = subprocess.run(
        [git, "ls-files", "--error-unmatch", "--", str(relative)],
        cwd=root,
        capture_output=True,
        check=False,
    )
    ignored = subprocess.run(
        [git, "check-ignore", "--quiet", "--", str(relative)],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if tracked.returncode == 0 or ignored.returncode != 0:
        raise BootstrapSnapshotError("Bootstrap evidence paths must remain outside Git.")


def default_enriched_snapshot_path(snapshot: BootstrapSnapshot, manifest_path: Path) -> Path:
    """Return the ignored, hash-addressed cache for raw-snapshot enrichment."""

    return manifest_path.resolve().parent / "source-snapshots" / f"{snapshot.sha256}.enriched.json"


def load_snapshot_for_manifest(
    manifest: Mapping[str, Any],
    *,
    required_available_through: datetime | None = None,
) -> BootstrapSnapshot:
    """Load the original snapshot and any immutable enrichment cache it names."""

    snapshot = load_bootstrap_snapshot(
        Path(str(manifest["snapshot_path"])),
        required_available_through=required_available_through,
    )
    cache_path = manifest.get("enriched_snapshot_path")
    if not isinstance(cache_path, str) or not cache_path.strip():
        return snapshot
    resolved_cache_path = Path(cache_path).resolve()
    if not resolved_cache_path.is_file():
        raise BootstrapSnapshotError("The enrichment cache is missing.")
    expected_hash = manifest.get("enriched_snapshot_sha256")
    actual_hash = hashlib.sha256(resolved_cache_path.read_bytes()).hexdigest()
    if expected_hash != actual_hash:
        raise BootstrapSnapshotError("The enrichment cache hash does not match the manifest.")
    return load_enriched_snapshot(resolved_cache_path, snapshot)


def write_enriched_snapshot(
    path: Path,
    source_snapshot: BootstrapSnapshot,
    parsed: CatalogParseResult,
) -> str:
    """Persist sanitized enrichment results so resume uses identical inputs."""

    document = {
        "schema_version": ENRICHED_CACHE_SCHEMA_VERSION,
        "source_snapshot_path": str(source_snapshot.path),
        "source_snapshot_sha256": source_snapshot.sha256,
        "rows": [_cached_row(row) for row in parsed.accepted_rows],
        "rejected_rows": [
            {
                "row_number": rejected.row_number,
                "diagnostic": _diagnostic_document(rejected.diagnostic),
            }
            for rejected in parsed.rejected_rows
        ],
    }
    write_run_manifest(path, document)
    return hashlib.sha256(path.resolve().read_bytes()).hexdigest()


def load_enriched_snapshot(
    path: Path,
    source_snapshot: BootstrapSnapshot,
) -> BootstrapSnapshot:
    """Load and validate one cache created from the bound raw snapshot."""

    try:
        document = json.loads(path.resolve().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BootstrapSnapshotError("The bootstrap enrichment cache could not be read.") from error
    if not isinstance(document, Mapping):
        raise BootstrapSnapshotError("The bootstrap enrichment cache must be an object.")
    if document.get("schema_version") != ENRICHED_CACHE_SCHEMA_VERSION:
        raise BootstrapSnapshotError("The bootstrap enrichment cache schema is invalid.")
    if document.get("source_snapshot_sha256") != source_snapshot.sha256:
        raise BootstrapSnapshotError("The enrichment cache does not match the source snapshot.")
    if Path(str(document.get("source_snapshot_path", ""))).resolve() != source_snapshot.path:
        raise BootstrapSnapshotError(
            "The enrichment cache path does not match the source snapshot."
        )
    rows = document.get("rows")
    rejected_rows = document.get("rejected_rows")
    if not isinstance(rows, list) or not isinstance(rejected_rows, list):
        raise BootstrapSnapshotError("The bootstrap enrichment cache rows are invalid.")
    try:
        accepted = tuple(_load_cached_row(value, index) for index, value in enumerate(rows, 1))
        rejected = tuple(_load_cached_rejection(value) for value in rejected_rows)
    except (BootstrapSnapshotError, _RejectedSnapshotRow, ValueError, TypeError) as error:
        raise BootstrapSnapshotError("The bootstrap enrichment cache rows are invalid.") from error
    _validate_enriched_cache(source_snapshot, accepted, rejected)
    return replace(
        source_snapshot,
        parsed=CatalogParseResult(accepted_rows=accepted, rejected_rows=rejected),
    )


def _validate_enriched_cache(
    source_snapshot: BootstrapSnapshot,
    accepted: tuple[NormalizedSourceRow, ...],
    rejected: tuple[RejectedSourceRow, ...],
) -> None:
    """Allow detail enrichment only; catalog evidence must remain byte-derived."""

    source_accepted = source_snapshot.parsed.accepted_rows
    source_rejected = source_snapshot.parsed.rejected_rows
    if len(accepted) != len(source_accepted) or rejected != source_rejected:
        raise BootstrapSnapshotError("The enrichment cache row evidence has changed.")
    for source, enriched in zip(source_accepted, accepted, strict=True):
        if _catalog_evidence(source) != _catalog_evidence(enriched):
            raise BootstrapSnapshotError("The enrichment cache changed catalog evidence.")
        source_minute = source.occurred_at.astimezone(UTC).replace(second=0, microsecond=0)
        enriched_minute = enriched.occurred_at.astimezone(UTC).replace(second=0, microsecond=0)
        if source_minute != enriched_minute:
            raise BootstrapSnapshotError("The enrichment cache changed the catalog minute.")


def _catalog_evidence(row: NormalizedSourceRow) -> tuple[object, ...]:
    return (
        row.latitude,
        row.longitude,
        row.depth_km,
        row.magnitude,
        row.location_description,
        row.source_bulletin_id,
        row.source_event_group_id,
        row.source_url,
    )


def load_run_manifest(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.resolve().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BootstrapSnapshotError("The bootstrap run manifest could not be read.") from error
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION
    ):
        raise BootstrapSnapshotError("The bootstrap run manifest schema is invalid.")
    for key in ("snapshot_path", "snapshot_sha256", "run_id", "correlation_id", "status"):
        if key not in document:
            raise BootstrapSnapshotError("The bootstrap run manifest is incomplete.")
    if not isinstance(document["snapshot_path"], str) or not document["snapshot_path"].strip():
        raise BootstrapSnapshotError("The bootstrap run manifest snapshot path is invalid.")
    if document["status"] not in {
        "prepared",
        "pending",
        "running",
        "retry_wait",
        "succeeded",
        "failed",
        "cancelled",
    }:
        raise BootstrapSnapshotError("The bootstrap run manifest status is invalid.")
    if not isinstance(document.get("counts"), dict):
        raise BootstrapSnapshotError("The bootstrap run manifest counts are invalid.")
    if not isinstance(document.get("diagnostics"), dict):
        raise BootstrapSnapshotError("The bootstrap run manifest diagnostics are invalid.")
    try:
        UUID(str(document["run_id"]))
        UUID(str(document["correlation_id"]))
    except (ValueError, TypeError) as error:
        raise BootstrapSnapshotError("The bootstrap run manifest IDs are invalid.") from error
    if not isinstance(document["snapshot_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", document["snapshot_sha256"]
    ):
        raise BootstrapSnapshotError("The bootstrap run manifest hash is invalid.")
    return document


def prepare_run_manifest(
    snapshot: BootstrapSnapshot,
    path: Path,
    *,
    enriched_snapshot_path: Path | None = None,
    enriched_snapshot_sha256: str | None = None,
) -> dict[str, Any]:
    """Create or verify the mutable operator sidecar before database work."""

    path = path.resolve()
    if path.exists():
        try:
            manifest = load_run_manifest(path)
        except BootstrapSnapshotError:
            if not _is_readiness_only_manifest(path):
                raise
        else:
            if manifest["snapshot_sha256"] != snapshot.sha256:
                raise BootstrapSnapshotError("The snapshot bytes do not match the run manifest.")
            if Path(str(manifest["snapshot_path"])).resolve() != snapshot.path:
                raise BootstrapSnapshotError("The snapshot path does not match the run manifest.")
            if manifest.get("enriched_snapshot_path") != (
                str(enriched_snapshot_path.resolve())
                if enriched_snapshot_path is not None
                else None
            ):
                raise BootstrapSnapshotError(
                    "The enrichment cache path does not match the run manifest."
                )
            if manifest.get("enriched_snapshot_sha256") != enriched_snapshot_sha256:
                raise BootstrapSnapshotError(
                    "The enrichment cache hash does not match the run manifest."
                )
            evidence_error = _snapshot_manifest_evidence_error(snapshot, manifest)
            if evidence_error is not None:
                raise BootstrapSnapshotError(evidence_error)
            return manifest

    manifest = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "snapshot_path": str(snapshot.path),
        "snapshot_sha256": snapshot.sha256,
        "run_id": str(uuid4()),
        "correlation_id": str(uuid4()),
        "status": "prepared",
        "snapshot_kind": snapshot.snapshot_kind,
        "alert_policy": "suppressed",
        "declared_row_count": snapshot.declared_row_count,
        "source_urls": list(snapshot.source_urls),
        "retrieved_at": snapshot.retrieved_at.isoformat(),
        "available_through": snapshot.available_through.isoformat(),
        "coverage": _coverage_document(snapshot.coverage),
        "diagnostics": snapshot.diagnostic_counts,
        "counts": {
            "snapshot_rows": snapshot.actual_row_count,
            "accepted_rows": len(snapshot.parsed.accepted_rows),
            "rejected_rows": len(snapshot.parsed.rejected_rows),
            "normalized_inputs": snapshot.normalized_input_count,
        },
    }
    if enriched_snapshot_path is not None:
        manifest["enriched_snapshot_path"] = str(enriched_snapshot_path.resolve())
        manifest["enriched_snapshot_sha256"] = enriched_snapshot_sha256
    write_run_manifest(path, manifest)
    return manifest


def _is_readiness_only_manifest(path: Path) -> bool:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(document, dict)
        and set(document) == {"schema_version", "readiness"}
        and document.get("schema_version") == RUN_MANIFEST_SCHEMA_VERSION
        and isinstance(document.get("readiness"), dict)
        and document["readiness"].get("schema_version") == READINESS_SCHEMA_VERSION
    )


def write_run_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    """Replace the sidecar atomically so an interrupted write is recoverable."""

    path = path.resolve()
    ensure_evidence_path_outside_git(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as error:
        raise BootstrapSnapshotError("The bootstrap run manifest could not be written.") from error
    finally:
        if temporary is not None and os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _cached_row(row: NormalizedSourceRow) -> dict[str, object]:
    return {
        "occurred_at": row.occurred_at.isoformat(),
        "time_precision": row.time_precision.value,
        "latitude": str(row.latitude),
        "longitude": str(row.longitude),
        "depth_km": str(row.depth_km),
        "magnitude": str(row.magnitude),
        "location_description": row.location_description,
        "source_bulletin_id": row.source_bulletin_id,
        "source_event_group_id": row.source_event_group_id,
        "source_url": row.source_url,
        "origin": row.origin,
        "diagnostics": [_diagnostic_document(diagnostic) for diagnostic in row.diagnostics],
    }


def _diagnostic_document(diagnostic: SourceDiagnostic) -> dict[str, object]:
    return {"code": diagnostic.code.value, "context": dict(diagnostic.context)}


def _load_cached_row(value: object, row_number: int) -> NormalizedSourceRow:
    if not isinstance(value, Mapping):
        raise BootstrapSnapshotError(f"Cached row {row_number} is invalid.")
    occurred_at = _aware_datetime(value.get("occurred_at"), f"rows[{row_number}].occurred_at")
    precision = value.get("time_precision")
    if precision not in {item.value for item in SourceTimePrecision}:
        raise BootstrapSnapshotError(f"Cached row {row_number} precision is invalid.")
    origin = value.get("origin")
    if origin is not None and not isinstance(origin, str):
        raise BootstrapSnapshotError(f"Cached row {row_number} origin is invalid.")
    diagnostics = value.get("diagnostics", [])
    if not isinstance(diagnostics, list):
        raise BootstrapSnapshotError(f"Cached row {row_number} diagnostics are invalid.")
    source_url = value.get("source_url")
    if not isinstance(source_url, str):
        raise BootstrapSnapshotError(f"Cached row {row_number} source URL is invalid.")
    row = _load_snapshot_row(
        {
            "occurred_at": occurred_at.isoformat(),
            "latitude": value.get("latitude"),
            "longitude": value.get("longitude"),
            "depth_km": value.get("depth_km"),
            "magnitude": value.get("magnitude"),
            "location_description": value.get("location_description"),
            "source_bulletin_id": value.get("source_bulletin_id"),
            "source_event_group_id": value.get("source_event_group_id"),
            "source_url": source_url,
        },
        row_number,
    )
    return replace(
        row,
        occurred_at=(
            occurred_at
            if precision == SourceTimePrecision.SECOND.value
            else occurred_at.replace(second=0, microsecond=0)
        ),
        time_precision=SourceTimePrecision(precision),
        origin=origin,
        diagnostics=tuple(_diagnostic(item) for item in diagnostics),
    )


def _load_cached_rejection(value: object) -> RejectedSourceRow:
    if not isinstance(value, Mapping):
        raise BootstrapSnapshotError("Cached rejected row is invalid.")
    row_number = value.get("row_number")
    if not isinstance(row_number, int) or isinstance(row_number, bool) or row_number <= 0:
        raise BootstrapSnapshotError("Cached rejected row number is invalid.")
    return RejectedSourceRow(row_number, _diagnostic(value.get("diagnostic")))


def write_startup_readiness_manifest(
    path: Path,
    report: StartupReport,
    *,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    """Atomically add a safe startup proof to an existing run manifest."""

    path = path.resolve()
    try:
        manifest = load_run_manifest(path) if path.exists() else None
    except BootstrapSnapshotError:
        manifest = None

    checked_at = checked_at or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise BootstrapSnapshotError("The readiness check time must include a timezone offset.")

    readiness = {
        "schema_version": READINESS_SCHEMA_VERSION,
        "checked_at": checked_at.isoformat(),
        "ready": report.ready,
        "failed_gate_names": list(report.failed_gate_names),
        "gates": [result.as_dict() for result in report.results],
        "history": _readiness_history(report),
        "database_counts": _readiness_database_counts(report),
        "model_release": _readiness_model_release(report),
    }
    document: dict[str, Any] = (
        dict(manifest) if manifest is not None else {"schema_version": RUN_MANIFEST_SCHEMA_VERSION}
    )
    document["readiness"] = readiness
    write_run_manifest(path, document)
    return document


def _readiness_history(report: StartupReport) -> dict[str, object]:
    details = _gate_details(report, "bootstrap-readiness")
    if "history_required_start" not in details:
        return {}
    result: dict[str, object] = {
        "anchor": details.get("history_anchor"),
        "required_start": details.get("history_required_start"),
        "required_end": details.get("history_required_end"),
        "coverage_start": details.get("history_coverage_start"),
        "coverage_end": details.get("history_coverage_end"),
        "coverage_complete": details.get("history_coverage_complete") == "true",
    }
    for key in ("history_observation_count", "usable_history_count"):
        if key in details:
            result[key.removeprefix("history_")] = int(details[key])
    return {key: value for key, value in result.items() if value is not None}


def _readiness_database_counts(report: StartupReport) -> dict[str, int]:
    details = _gate_details(report, "bootstrap-readiness")
    value = details.get("database_counts")
    if value is None:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(count, int) and not isinstance(count, bool)
        for key, count in parsed.items()
    ):
        return {}
    return parsed


def _readiness_model_release(report: StartupReport) -> dict[str, object]:
    details = _gate_details(report, "model-release")
    if "release_id" not in details:
        return {}
    result: dict[str, object] = {
        key: details[key]
        for key in (
            "release_id",
            "version_label",
            "manifest_uri",
            "manifest_hash",
            "input_schema_version",
            "output_schema_version",
        )
        if key in details
    }
    artifact_hashes = details.get("artifact_hashes")
    if artifact_hashes is not None:
        try:
            parsed = json.loads(artifact_hashes)
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict) and all(
            isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()
        ):
            result["artifact_hashes"] = parsed
    return result


def _gate_details(report: StartupReport, name: str) -> dict[str, str]:
    for result in report.results:
        if result.name == name:
            return dict(result.details)
    return {}


def _load_snapshot_row(
    value: object,
    row_number: int,
    *,
    snapshot_kind: str = "raw",
) -> NormalizedSourceRow:
    if not isinstance(value, Mapping):
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW))
    _reject_embedded_raw_payload(value)
    catalog = value.get("catalog", value)
    if not isinstance(catalog, Mapping):
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW))
    _reject_embedded_raw_payload(catalog)
    supplied_detail = value.get("detail")
    if isinstance(supplied_detail, Mapping):
        _reject_embedded_raw_payload(supplied_detail)
    detail = supplied_detail if snapshot_kind == "enriched" else None
    try:
        occurred_at = _aware_datetime(catalog.get("occurred_at"), "row.occurred_at")
        source_url = catalog.get("source_url")
        if not isinstance(source_url, str) or not source_url.strip():
            raise BulletinUrlRejected("source URL is missing")
        identity = canonicalize_bulletin_url(source_url, source_url, occurred_at.year)
        bulletin_id = _optional_text(catalog.get("source_bulletin_id"), "source_bulletin_id")
        group_id = _optional_text(catalog.get("source_event_group_id"), "source_event_group_id")
        if bulletin_id is not None and (
            identity.source_bulletin_id is None
            or bulletin_id.strip().upper() != identity.source_bulletin_id
        ):
            raise ValueError("source identifiers disagree")
        if group_id is not None and group_id.strip().upper() != identity.source_event_group_id:
            raise ValueError("source identifiers disagree")
        if bulletin_id is None and group_id is None:
            raise ValueError("source identifier is missing")
        row = NormalizedSourceRow.from_catalog_values(
            occurred_at=occurred_at,
            latitude=_required_value(catalog, "latitude"),
            longitude=_required_value(catalog, "longitude"),
            depth_km=_required_value(catalog, "depth_km"),
            magnitude=_required_value(catalog, "magnitude"),
            location_description=_required_text(catalog, "location_description"),
            source_bulletin_id=bulletin_id,
            source_event_group_id=group_id,
            source_url=identity.source_url,
        )
    except BulletinUrlRejected as error:
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_SOURCE_URL)) from error
    except _RejectedSnapshotRow:
        raise
    except BootstrapSnapshotError as error:
        raise _RejectedSnapshotRow(_row_diagnostic(error)) from error
    except ValueError as error:
        raise _RejectedSnapshotRow(_row_diagnostic(error)) from error
    except (KeyError, TypeError) as error:
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW)) from error
    if snapshot_kind == "enriched" and (
        not isinstance(detail, Mapping) or detail.get("status") not in {"enriched", "failed"}
    ):
        raise BootstrapSnapshotError(
            "Each valid row in an enriched snapshot must include a completed detail result."
        )
    return _apply_detail(row, detail)


def _apply_detail(row: NormalizedSourceRow, value: object) -> NormalizedSourceRow:
    if value is None:
        return row
    if not isinstance(value, Mapping):
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW))
    status = value.get("status", "not_attempted")
    if status not in _ALLOWED_DETAIL_STATUSES:
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW))
    occurred_at = value.get("occurred_at") if status == "enriched" else None
    detail_time = (
        _aware_datetime(occurred_at, "detail.occurred_at") if occurred_at is not None else None
    )
    origin = value.get("origin") if status == "enriched" else None
    if origin is not None and not isinstance(origin, str):
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW))
    diagnostic_values = value.get("diagnostics", [])
    if not isinstance(diagnostic_values, list):
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW))
    diagnostics_list = [_diagnostic(item) for item in diagnostic_values]
    if status == "enriched" and detail_time is None:
        diagnostics_list.append(SourceDiagnostic(DiagnosticCode.DETAIL_TIMESTAMP_MISSING))
    if status == "failed" and not any(
        diagnostic.code in _DETAIL_FAILURE_CODES for diagnostic in diagnostics_list
    ):
        diagnostics_list.append(SourceDiagnostic(DiagnosticCode.DETAIL_FETCH_FAILED))
    normalized_origin = (
        normalize_detail_origin(origin, diagnostics_list) if status == "enriched" else None
    )
    return row.with_detail_enrichment(
        detail_occurred_at=detail_time,
        origin=normalized_origin,
        diagnostics=tuple(diagnostics_list),
    )


def _diagnostic(value: object) -> SourceDiagnostic:
    if isinstance(value, str):
        return SourceDiagnostic(DiagnosticCode(value))
    if not isinstance(value, Mapping):
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW))
    code = value.get("code")
    context = value.get("context", {})
    if not isinstance(code, str) or not isinstance(context, Mapping):
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW))
    try:
        return SourceDiagnostic(DiagnosticCode(code), context)
    except (ValueError, TypeError) as error:
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW)) from error


def _reject_embedded_raw_payload(value: Mapping[object, object]) -> None:
    if _FORBIDDEN_EMBEDDED_PAYLOAD_KEYS.intersection(value):
        raise BootstrapSnapshotError("Raw HTML or exception text is not allowed in the snapshot.")


def _row_diagnostic(error: ValueError) -> SourceDiagnostic:
    message = str(error)
    if "source_" in message or "identifier" in message:
        return SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW)
    if "timestamp" in message or "occurred_at" in message:
        return SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_TIMESTAMP)
    if any(field in message for field in ("latitude", "longitude", "depth_km", "magnitude")):
        return SourceDiagnostic(DiagnosticCode.INVALID_NUMERIC_VALUE)
    return SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW)


def _validate_coverage(
    coverage: SnapshotCoverage,
    retrieved_at: datetime,
    available_through: datetime,
    required_available_through: datetime | None,
) -> None:
    if coverage.end <= coverage.start:
        raise BootstrapSnapshotError("coverage.end must be after coverage.start.")
    anchor_local = coverage.first_prediction_anchor.astimezone(MANILA)
    if anchor_local.year != 2026 or anchor_local.month != 9:
        raise BootstrapSnapshotError("first_prediction_anchor must be in September 2026.")
    if not coverage.start <= coverage.first_prediction_anchor < coverage.end:
        raise BootstrapSnapshotError("first_prediction_anchor must be inside coverage.")
    available_local = available_through.astimezone(MANILA)
    if available_local.year != 2026 or available_local.month != 9:
        raise BootstrapSnapshotError("source.available_through must be in September 2026.")
    if available_through > retrieved_at:
        raise BootstrapSnapshotError("source.available_through cannot be after retrieval.")
    if required_available_through is not None and available_through.astimezone(
        UTC
    ) < required_available_through.astimezone(UTC):
        raise BootstrapSnapshotError(
            "source.available_through does not reach the configured September cutoff."
        )
    if not coverage.start <= available_through < coverage.end:
        raise BootstrapSnapshotError("source.available_through must be inside coverage.")


def _validate_import_coverage(
    rows: list[NormalizedSourceRow],
    coverage: SnapshotCoverage,
    available_through: datetime,
) -> None:
    """Reject an incomplete history window before any durable import starts."""

    if not coverage.complete:
        raise BootstrapSnapshotError("The bootstrap snapshot coverage is not complete.")
    if coverage.start.astimezone(UTC) > _MINIMUM_LOOKBACK_START.astimezone(UTC):
        raise BootstrapSnapshotError(
            "The bootstrap snapshot starts after the required August lookback."
        )
    if not rows:
        raise BootstrapSnapshotError("The bootstrap snapshot contains no accepted source rows.")
    actual_start = min(row.occurred_at for row in rows)
    actual_end = max(row.occurred_at for row in rows)
    if actual_start.astimezone(UTC) > _MINIMUM_LOOKBACK_START.astimezone(UTC):
        raise BootstrapSnapshotError(
            "Accepted source rows do not reach the required August lookback."
        )
    if actual_end.astimezone(UTC) < coverage.first_prediction_anchor.astimezone(UTC):
        raise BootstrapSnapshotError(
            "Accepted source rows do not reach the first prediction anchor."
        )
    if actual_end.astimezone(UTC) < available_through.astimezone(UTC):
        raise BootstrapSnapshotError(
            "Accepted source rows do not reach the available September window."
        )
    final_covered_day = (coverage.end - timedelta(microseconds=1)).astimezone(MANILA).date()
    if actual_end.astimezone(MANILA).date() < final_covered_day:
        raise BootstrapSnapshotError("Accepted source rows do not reach the declared coverage end.")


def _validate_rows_against_coverage(
    rows: list[NormalizedSourceRow], coverage: SnapshotCoverage
) -> None:
    for row in rows:
        if row.occurred_at < coverage.start or row.occurred_at >= coverage.end:
            raise BootstrapSnapshotError("A snapshot row falls outside declared coverage.")


def _coverage_document(coverage: SnapshotCoverage) -> dict[str, object]:
    return {
        "start": coverage.start.isoformat(),
        "end": coverage.end.isoformat(),
        "complete": coverage.complete,
        "first_prediction_anchor": coverage.first_prediction_anchor.isoformat(),
    }


def _source_urls(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise BootstrapSnapshotError("source.catalog_urls must be a nonempty array.")
    urls: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise BootstrapSnapshotError("source.catalog_urls must contain strings.")
        parsed = item.strip()
        url = urlsplit(parsed)
        if (
            url.scheme != "https"
            or url.hostname != OFFICIAL_HOST
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or " " in parsed
        ):
            raise BootstrapSnapshotError("source.catalog_urls must contain HTTPS URLs.")
        urls.append(parsed)
    return tuple(urls)


def _required_mapping(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    result = value.get(key)
    if not isinstance(result, Mapping):
        raise BootstrapSnapshotError(f"{key} must be an object.")
    return result


def _required_text(value: Mapping[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise BootstrapSnapshotError(f"{key} must be nonblank text.")
    return result.strip()


def _optional_text(value: object, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} is invalid")
    return value


def _required_value(value: Mapping[str, object], key: str) -> object:
    if key not in value:
        raise ValueError(f"{key} is missing")
    return value[key]


def _required_bool(value: Mapping[str, object], key: str) -> bool:
    result = value.get(key)
    if not isinstance(result, bool):
        raise BootstrapSnapshotError(f"{key} must be boolean.")
    return result


def _aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise BootstrapSnapshotError(f"{field} must be an ISO timestamp.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise BootstrapSnapshotError(f"{field} must be an ISO timestamp.") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise BootstrapSnapshotError(f"{field} must include a timezone offset.")
    return result


def _row_number(value: object, fallback: int) -> int:
    if (
        isinstance(value, Mapping)
        and isinstance(value.get("row_number"), int)
        and not isinstance(value.get("row_number"), bool)
    ):
        candidate = value["row_number"]
        if candidate > 0:
            return candidate
    return fallback


class _RejectedSnapshotRow(Exception):
    def __init__(self, diagnostic: SourceDiagnostic) -> None:
        super().__init__(diagnostic.code.value)
        self.diagnostic = diagnostic
