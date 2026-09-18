"""Bootstrap snapshot validation and ignored operator evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from quakestrike.domain.features import HistoryCoverage, evaluate_history_readiness
from quakestrike.domain.source_rows import (
    CatalogParseResult,
    DiagnosticCode,
    NormalizedSourceRow,
    RejectedSourceRow,
    SourceDiagnostic,
)
from quakestrike.infrastructure.phivolcs.parser import normalize_detail_origin
from quakestrike.infrastructure.phivolcs.urls import (
    OFFICIAL_HOST,
    BulletinUrlRejected,
    canonicalize_bulletin_url,
)

SNAPSHOT_SCHEMA_VERSION = "quakestrike.bootstrap-snapshot.v1"
RUN_MANIFEST_SCHEMA_VERSION = "quakestrike.bootstrap-run.v1"
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
    coverage: SnapshotCoverage
    declared_row_count: int
    parsed: CatalogParseResult

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
) -> BootstrapReadiness:
    """Prove that one completed sidecar and its database run are safe to start from."""

    if manifest.get("snapshot_sha256") != snapshot.sha256:
        return _not_ready("The run manifest hash does not match the snapshot.")
    if Path(str(manifest.get("snapshot_path", ""))).resolve() != snapshot.path:
        return _not_ready("The run manifest path does not match the snapshot.")
    if manifest.get("snapshot_kind") != snapshot.snapshot_kind:
        return _not_ready("The run manifest snapshot kind does not match the snapshot.")
    if manifest.get("declared_row_count") != snapshot.declared_row_count:
        return _not_ready("The run manifest row count does not match the snapshot.")
    if manifest.get("coverage") != _coverage_document(snapshot.coverage):
        return _not_ready("The run manifest coverage does not match the snapshot.")
    if manifest.get("diagnostics") != snapshot.diagnostic_counts:
        return _not_ready("The run manifest diagnostics do not match the snapshot.")
    if manifest.get("alert_policy") != "suppressed":
        return _not_ready("The bootstrap alert policy is not explicitly suppressed.")
    if run_state is None:
        return _not_ready("The durable bootstrap run does not exist.")
    if getattr(run_state, "trigger_type", None) != "backfill":
        return _not_ready("The durable run is not a backfill run.")
    if getattr(run_state, "status", None) != "succeeded":
        return _not_ready("The durable bootstrap run has not succeeded.")
    if manifest.get("status") != "succeeded":
        return _not_ready("The run manifest has not recorded a successful run.")
    if str(getattr(run_state, "run_id", "")) != str(manifest.get("run_id", "")):
        return _not_ready("The run manifest and durable run IDs do not match.")
    if str(getattr(run_state, "correlation_id", "")) != str(manifest.get("correlation_id", "")):
        return _not_ready("The run manifest and durable correlation IDs do not match.")

    counts = manifest.get("counts")
    if not isinstance(counts, Mapping):
        return _not_ready("The run manifest does not contain durable counts.")
    expected_snapshot_counts = {
        "snapshot_rows": snapshot.actual_row_count,
        "accepted_rows": len(snapshot.parsed.accepted_rows),
        "rejected_rows": len(snapshot.parsed.rejected_rows),
        "normalized_inputs": snapshot.normalized_input_count,
    }
    for key, expected in expected_snapshot_counts.items():
        if counts.get(key) != expected:
            return _not_ready(f"The run manifest {key} count is inconsistent.")
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
    return BootstrapReadiness(
        ready=True,
        reason="Bootstrap snapshot, durable run, and history coverage are ready.",
        details={
            "run_id": str(run_state.run_id),
            "snapshot_sha256": snapshot.sha256,
            "checkpointed_inputs": str(run_state.events_found),
        },
    )


def _not_ready(reason: str) -> BootstrapReadiness:
    return BootstrapReadiness(ready=False, reason=reason, details={})


def load_bootstrap_snapshot(path: Path) -> BootstrapSnapshot:
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
    _validate_coverage(coverage)

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
            accepted.append(_load_snapshot_row(value, row_number))
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
    return BootstrapSnapshot(
        path=path.resolve(),
        sha256=digest,
        snapshot_kind=snapshot_kind,
        source_urls=source_urls,
        retrieved_at=retrieved_at,
        coverage=coverage,
        declared_row_count=declared_row_count,
        parsed=CatalogParseResult(tuple(accepted), tuple(rejected)),
    )


def default_run_manifest_path(snapshot_path: Path) -> Path:
    """Return the predictable ignored sidecar path for one snapshot."""

    return snapshot_path.with_name(snapshot_path.name + ".bootstrap.json")


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


def prepare_run_manifest(snapshot: BootstrapSnapshot, path: Path) -> dict[str, Any]:
    """Create or verify the mutable operator sidecar before database work."""

    path = path.resolve()
    if path.exists():
        manifest = load_run_manifest(path)
        if manifest["snapshot_sha256"] != snapshot.sha256:
            raise BootstrapSnapshotError("The snapshot bytes do not match the run manifest.")
        if Path(str(manifest["snapshot_path"])).resolve() != snapshot.path:
            raise BootstrapSnapshotError("The snapshot path does not match the run manifest.")
        expected_counts = {
            "snapshot_rows": snapshot.actual_row_count,
            "accepted_rows": len(snapshot.parsed.accepted_rows),
            "rejected_rows": len(snapshot.parsed.rejected_rows),
            "normalized_inputs": snapshot.normalized_input_count,
        }
        if (
            manifest.get("snapshot_kind") != snapshot.snapshot_kind
            or manifest.get("alert_policy") != "suppressed"
            or manifest.get("declared_row_count") != snapshot.declared_row_count
            or manifest.get("source_urls") != list(snapshot.source_urls)
            or manifest.get("retrieved_at") != snapshot.retrieved_at.isoformat()
            or manifest.get("coverage") != _coverage_document(snapshot.coverage)
            or manifest.get("diagnostics") != snapshot.diagnostic_counts
            or any(
                manifest.get("counts", {}).get(key) != value
                for key, value in expected_counts.items()
            )
        ):
            raise BootstrapSnapshotError("The run manifest evidence does not match the snapshot.")
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
        "coverage": _coverage_document(snapshot.coverage),
        "diagnostics": snapshot.diagnostic_counts,
        "counts": {
            "snapshot_rows": snapshot.actual_row_count,
            "accepted_rows": len(snapshot.parsed.accepted_rows),
            "rejected_rows": len(snapshot.parsed.rejected_rows),
            "normalized_inputs": snapshot.normalized_input_count,
        },
    }
    write_run_manifest(path, manifest)
    return manifest


def write_run_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    """Replace the sidecar atomically so an interrupted write is recoverable."""

    path = path.resolve()
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


def _load_snapshot_row(value: object, row_number: int) -> NormalizedSourceRow:
    if not isinstance(value, Mapping):
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW))
    _reject_embedded_raw_payload(value)
    catalog = value.get("catalog", value)
    if not isinstance(catalog, Mapping):
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW))
    _reject_embedded_raw_payload(catalog)
    detail = value.get("detail")
    if isinstance(detail, Mapping):
        _reject_embedded_raw_payload(detail)
    try:
        occurred_at = _aware_datetime(catalog.get("occurred_at"), "row.occurred_at")
        source_url = catalog.get("source_url")
        if not isinstance(source_url, str) or not source_url.strip():
            raise BulletinUrlRejected("source URL is missing")
        identity = canonicalize_bulletin_url(source_url, source_url, occurred_at.year)
        bulletin_id = _optional_text(catalog.get("source_bulletin_id"), "source_bulletin_id")
        group_id = _optional_text(catalog.get("source_event_group_id"), "source_event_group_id")
        if (
            bulletin_id is not None
            and identity.source_bulletin_id is not None
            and bulletin_id.strip().upper() != identity.source_bulletin_id
        ):
            raise ValueError("source identifiers disagree")
        if group_id is not None and group_id.strip().upper() != identity.source_event_group_id:
            raise ValueError("source identifiers disagree")
        row = NormalizedSourceRow.from_catalog_values(
            occurred_at=occurred_at,
            latitude=_required_value(catalog, "latitude"),
            longitude=_required_value(catalog, "longitude"),
            depth_km=_required_value(catalog, "depth_km"),
            magnitude=_required_value(catalog, "magnitude"),
            location_description=_required_text(catalog, "location_description"),
            source_bulletin_id=bulletin_id or identity.source_bulletin_id,
            source_event_group_id=group_id or identity.source_event_group_id,
            source_url=identity.source_url,
        )
        return _apply_detail(row, detail)
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


def _apply_detail(row: NormalizedSourceRow, value: object) -> NormalizedSourceRow:
    if value is None:
        return row
    if not isinstance(value, Mapping):
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW))
    status = value.get("status", "not_attempted")
    if status not in _ALLOWED_DETAIL_STATUSES:
        raise _RejectedSnapshotRow(SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW))
    occurred_at = value.get("occurred_at")
    detail_time = (
        _aware_datetime(occurred_at, "detail.occurred_at") if occurred_at is not None else None
    )
    origin = value.get("origin")
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
        normalize_detail_origin(origin, diagnostics_list)
        if status == "enriched" or origin is not None
        else None
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


def _validate_coverage(coverage: SnapshotCoverage) -> None:
    if coverage.end <= coverage.start:
        raise BootstrapSnapshotError("coverage.end must be after coverage.start.")
    anchor_local = coverage.first_prediction_anchor.astimezone(MANILA)
    if anchor_local.year != 2026 or anchor_local.month != 9:
        raise BootstrapSnapshotError("first_prediction_anchor must be in September 2026.")
    if not coverage.start <= coverage.first_prediction_anchor < coverage.end:
        raise BootstrapSnapshotError("first_prediction_anchor must be inside coverage.")


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
