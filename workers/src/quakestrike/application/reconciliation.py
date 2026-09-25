"""Ingestion-run orchestration for normalized PHIVOLCS source observations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from quakestrike.application.persistence import (
    EventRevisionRequest,
    EventTransactionResult,
    FatalIdentityConflict,
    FeatureEventTransactionRequest,
    RunClaim,
)
from quakestrike.application.phivolcs import (
    CatalogRetrievalError,
    CatalogRetrievalLeaseLost,
    CurrentCatalogRetriever,
)
from quakestrike.domain.features import HISTORY_WINDOW, HistoryCoverage
from quakestrike.domain.reconciliation import (
    EventCandidate,
    ReconciliationAction,
    choose_group_fallback,
)
from quakestrike.domain.source_rows import (
    CatalogEvidence,
    CatalogParseResult,
    NormalizedSourceRow,
    SourceDiagnostic,
)


class DuplicateBulletinConflict(ValueError):
    """One source page published incompatible values for a canonical bulletin ID."""


class CatalogEvidenceConflict(ValueError):
    """One logical run cannot reconcile two different catalog responses."""


@dataclass(frozen=True, slots=True)
class ReconciliationRunResult:
    """The completed state observed by the caller after one execution attempt."""

    status: str
    claimed: bool


@dataclass(frozen=True, slots=True)
class ReconciliationDiagnostic:
    """One sanitized row diagnostic with durable run and input correlation."""

    run_id: UUID
    worker_execution_id: UUID
    correlation_id: UUID
    input_key: str
    code: str


class ReconciliationDiagnosticReporter(Protocol):
    """Emits one safe diagnostic for a parser, enrichment, or identity outcome."""

    def report(self, diagnostic: ReconciliationDiagnostic) -> None: ...


SourceRowsLoader = Callable[..., CatalogParseResult]


class ReconciliationStore(Protocol):
    """Persistence boundary for Phase 5 orchestration."""

    def claim_run(
        self, run_id: UUID, worker_execution_id: UUID, now: datetime
    ) -> RunClaim | None: ...

    def heartbeat_run(self, run_id: UUID, worker_execution_id: UUID, now: datetime) -> bool: ...

    def bind_catalog_evidence(
        self, run_id: UUID, worker_execution_id: UUID, evidence: CatalogEvidence
    ) -> CatalogEvidence: ...

    def successful_catalog_coverages(
        self, needed_start: datetime, needed_end: datetime
    ) -> tuple[HistoryCoverage, ...]: ...

    def checkpoint_input(
        self,
        run_id: UUID,
        worker_execution_id: UUID,
        input_key: str,
        outcome: str,
        event_id: UUID | None,
    ) -> bool: ...

    def input_checkpoint_exists(self, run_id: UUID, input_key: str) -> bool: ...

    def find_event_by_bulletin_id(self, source_bulletin_id: str) -> UUID | None: ...

    def find_group_candidates(self, source_event_group_id: str) -> Iterable[object]: ...

    def process_event_with_features(self, request: FeatureEventTransactionRequest): ...

    def counters_for_run(self, run_id: UUID, worker_execution_id: UUID): ...

    def complete_run(
        self, run_id: UUID, worker_execution_id: UUID, now: datetime, counters: object
    ) -> bool: ...

    def fail_run(
        self,
        run_id: UUID,
        worker_execution_id: UUID,
        now: datetime,
        error_code: str,
        error_message: str,
        *,
        retryable: bool,
    ) -> str | None: ...


class ReconcileSourceRows:
    """Claim a run, reconcile one source snapshot, and persist restart-safe progress."""

    def __init__(
        self,
        *,
        store: ReconciliationStore,
        source_loader: SourceRowsLoader,
        diagnostic_reporter: ReconciliationDiagnosticReporter,
        model_release_id: UUID,
        history_coverage: HistoryCoverage | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        new_uuid: Callable[[], UUID] = uuid4,
        event_reporter: Callable[[RunClaim, EventTransactionResult], None] | None = None,
    ) -> None:
        self._store = store
        self._source_loader = source_loader
        self._diagnostic_reporter = diagnostic_reporter
        self._model_release_id = model_release_id
        self._history_coverage = history_coverage
        self._now = now
        self._new_uuid = new_uuid
        self._event_reporter = event_reporter

    def execute(self, run_id: UUID) -> ReconciliationRunResult:
        """Run one fenced attempt. Queue redelivery uses the same run ID."""

        execution_id = self._new_uuid()
        claim = self._store.claim_run(run_id, execution_id, self._now())
        if claim is None:
            return ReconciliationRunResult(status="not_claimed", claimed=False)
        try:
            parsed = self._source_loader(
                heartbeat=lambda: self._store.heartbeat_run(
                    claim.run_id, claim.worker_execution_id, self._now()
                )
            )
            rows = sorted(
                coalesce_catalog_rows(parsed),
                key=lambda row: (row.occurred_at, row.source_bulletin_id or ""),
            )
            coverages = [self._history_coverage] if self._history_coverage is not None else []
            if parsed.evidence is not None:
                evidence = self._store.bind_catalog_evidence(
                    claim.run_id, claim.worker_execution_id, parsed.evidence
                )
                coverages.extend(
                    self._store.successful_catalog_coverages(
                        evidence.coverage_start - HISTORY_WINDOW,
                        evidence.coverage_end,
                    )
                )
                coverages.append(
                    HistoryCoverage(evidence.coverage_start, evidence.coverage_end, True)
                )
            merged_coverages = merge_history_coverages(coverages)
            for rejected in parsed.rejected_rows:
                input_key = _rejected_input_key(rejected.row_number, rejected.diagnostic.code)
                if self._store.input_checkpoint_exists(claim.run_id, input_key):
                    continue
                checkpointed = self._store.checkpoint_input(
                    claim.run_id,
                    claim.worker_execution_id,
                    input_key,
                    "rejected",
                    None,
                )
                if checkpointed:
                    self._report_diagnostic(claim, input_key, rejected.diagnostic)
            for row in rows:
                self._process_row(
                    claim, row, coverage_for_anchor(row.occurred_at, merged_coverages)
                )
                if not self._store.heartbeat_run(
                    claim.run_id, claim.worker_execution_id, self._now()
                ):
                    return ReconciliationRunResult(status="lease_lost", claimed=True)
            counters = self._store.counters_for_run(claim.run_id, claim.worker_execution_id)
            completed = self._store.complete_run(
                claim.run_id, claim.worker_execution_id, self._now(), counters
            )
            return ReconciliationRunResult(
                status="succeeded" if completed else "lease_lost", claimed=True
            )
        except DuplicateBulletinConflict:
            status = self._store.fail_run(
                claim.run_id,
                claim.worker_execution_id,
                self._now(),
                "CONFLICTING_DUPLICATE_BULLETIN",
                "The catalog contains conflicting values for one bulletin ID.",
                retryable=False,
            )
            return ReconciliationRunResult(status=status or "lease_lost", claimed=True)
        except CatalogEvidenceConflict:
            status = self._store.fail_run(
                claim.run_id,
                claim.worker_execution_id,
                self._now(),
                "CATALOG_EVIDENCE_CONFLICT",
                "A retry fetched different catalog content for this run.",
                retryable=False,
            )
            return ReconciliationRunResult(status=status or "lease_lost", claimed=True)
        except FatalIdentityConflict:
            status = self._store.fail_run(
                claim.run_id,
                claim.worker_execution_id,
                self._now(),
                "BULLETIN_EVENT_IDENTITY_CONFLICT",
                "The bulletin identity conflicts with the existing event mapping.",
                retryable=False,
            )
            return ReconciliationRunResult(status=status or "lease_lost", claimed=True)
        except CatalogRetrievalLeaseLost:
            return ReconciliationRunResult(status="lease_lost", claimed=True)
        except CatalogRetrievalError as error:
            if error.category == "catalog_structure":
                status = self._store.fail_run(
                    claim.run_id,
                    claim.worker_execution_id,
                    self._now(),
                    "CATALOG_STRUCTURE_INVALID",
                    "The current catalog does not contain a valid event table.",
                    retryable=False,
                )
                return ReconciliationRunResult(status=status or "lease_lost", claimed=True)
            retryable = error.category in {"request_failed", "transient_http"}
            status = self._store.fail_run(
                claim.run_id,
                claim.worker_execution_id,
                self._now(),
                "CATALOG_TRANSPORT_FAILURE",
                "The current catalog could not be retrieved.",
                retryable=retryable,
            )
            return ReconciliationRunResult(status=status or "lease_lost", claimed=True)
        except Exception:
            status = self._store.fail_run(
                claim.run_id,
                claim.worker_execution_id,
                self._now(),
                "RECONCILIATION_PERSISTENCE_FAILURE",
                "The run could not persist reconciliation progress.",
                retryable=True,
            )
            return ReconciliationRunResult(status=status or "lease_lost", claimed=True)

    def _process_row(
        self,
        claim: RunClaim,
        row: NormalizedSourceRow,
        history_coverage: HistoryCoverage | None,
    ) -> None:
        input_key = normalized_input_key(row)
        if self._store.input_checkpoint_exists(claim.run_id, input_key):
            return
        for diagnostic in row.diagnostics:
            self._report_diagnostic(claim, input_key, diagnostic)
        existing_event_id = (
            self._store.find_event_by_bulletin_id(row.source_bulletin_id)
            if row.source_bulletin_id is not None
            else None
        )
        if existing_event_id is None:
            candidates = ()
            if row.source_event_group_id is not None:
                candidates = tuple(
                    EventCandidate(
                        event_id=candidate.event_id,
                        source_event_group_id=candidate.source_event_group_id,
                        latitude=candidate.latitude,
                        longitude=candidate.longitude,
                        magnitude=candidate.magnitude,
                    )
                    for candidate in self._store.find_group_candidates(row.source_event_group_id)
                )
            decision = choose_group_fallback(row, candidates)
            if decision.action is ReconciliationAction.ATTACH:
                existing_event_id = decision.event_id
            elif row.source_bulletin_id is None:
                if self._store.checkpoint_input(
                    claim.run_id, claim.worker_execution_id, input_key, "rejected", None
                ):
                    self._report_rejection(claim, input_key, decision.rejection_code)
                return
            elif decision.rejection_code == "AMBIGUOUS_FALLBACK":
                if self._store.checkpoint_input(
                    claim.run_id, claim.worker_execution_id, input_key, "rejected", None
                ):
                    self._report_rejection(claim, input_key, decision.rejection_code)
                return

        event_id = existing_event_id or self._new_uuid()
        result = self._store.process_event_with_features(
            FeatureEventTransactionRequest(
                event_id=event_id,
                ingestion_run_id=claim.run_id,
                worker_execution_id=claim.worker_execution_id,
                input_key=input_key,
                model_release_id=self._model_release_id,
                correlation_id=claim.correlation_id,
                history_coverage=history_coverage,
                revision=EventRevisionRequest(
                    event_revision_id=self._new_uuid(),
                    ingestion_run_id=claim.run_id,
                    source_bulletin_id=row.source_bulletin_id,
                    source_event_group_id=row.source_event_group_id,
                    source_url=row.source_url,
                    source_time_precision=row.time_precision.value,
                    event_time=row.occurred_at,
                    latitude=row.latitude,
                    longitude=row.longitude,
                    depth_km=row.depth_km,
                    magnitude=row.magnitude,
                    location_description=row.location_description,
                    origin=row.origin,
                ),
            )
        )
        if self._event_reporter is not None:
            self._event_reporter(claim, result)

    def _report_diagnostic(
        self,
        claim: RunClaim,
        input_key: str,
        diagnostic: SourceDiagnostic,
    ) -> None:
        self._diagnostic_reporter.report(
            ReconciliationDiagnostic(
                claim.run_id,
                claim.worker_execution_id,
                claim.correlation_id,
                input_key,
                diagnostic.code.value,
            )
        )

    def _report_rejection(
        self,
        claim: RunClaim,
        input_key: str,
        code: str | None,
    ) -> None:
        self._diagnostic_reporter.report(
            ReconciliationDiagnostic(
                claim.run_id,
                claim.worker_execution_id,
                claim.correlation_id,
                input_key,
                code or "REJECTED_ROW",
            )
        )


class ReconcileCurrentCatalog(ReconcileSourceRows):
    """Adapt the live PHIVOLCS retriever to the shared source-row pipeline."""

    def __init__(
        self,
        *,
        store: ReconciliationStore,
        retriever: CurrentCatalogRetriever,
        diagnostic_reporter: ReconciliationDiagnosticReporter,
        model_release_id: UUID,
        history_coverage: HistoryCoverage | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        new_uuid: Callable[[], UUID] = uuid4,
        event_reporter: Callable[[RunClaim, EventTransactionResult], None] | None = None,
    ) -> None:
        super().__init__(
            store=store,
            source_loader=retriever.retrieve_current_catalog,
            diagnostic_reporter=diagnostic_reporter,
            model_release_id=model_release_id,
            history_coverage=history_coverage,
            now=now,
            new_uuid=new_uuid,
            event_reporter=event_reporter,
        )


def merge_history_coverages(
    coverages: Iterable[HistoryCoverage],
) -> tuple[HistoryCoverage, ...]:
    """Keep disjoint source intervals separate so gaps cannot become zero counts."""

    complete = sorted(
        (
            coverage
            for coverage in coverages
            if coverage.complete and coverage.start and coverage.end
        ),
        key=lambda coverage: coverage.start,
    )
    merged: list[HistoryCoverage] = []
    for coverage in complete:
        previous = merged[-1] if merged else None
        if previous is not None and coverage.start <= previous.end:
            merged[-1] = HistoryCoverage(previous.start, max(previous.end, coverage.end), True)
        else:
            merged.append(coverage)
    return tuple(merged)


def coverage_for_anchor(
    anchor_time: datetime, coverages: Iterable[HistoryCoverage]
) -> HistoryCoverage | None:
    available = tuple(coverages)
    return next(
        (
            coverage
            for coverage in available
            if coverage.start is not None
            and coverage.end is not None
            and coverage.start <= anchor_time <= coverage.end
        ),
        available[0] if available else None,
    )


def coalesce_catalog_rows(parsed: CatalogParseResult) -> tuple[NormalizedSourceRow, ...]:
    """Coalesce equivalent repeated bulletins and reject conflicting source pages."""

    rows_by_bulletin: dict[str, NormalizedSourceRow] = {}
    rows_without_bulletin: list[NormalizedSourceRow] = []
    for row in parsed.accepted_rows:
        if row.source_bulletin_id is None:
            rows_without_bulletin.append(row)
            continue
        existing = rows_by_bulletin.get(row.source_bulletin_id)
        if existing is None:
            rows_by_bulletin[row.source_bulletin_id] = row
        elif persisted_row_values(existing) != persisted_row_values(row):
            raise DuplicateBulletinConflict(row.source_bulletin_id)
    return tuple(rows_by_bulletin.values()) + tuple(rows_without_bulletin)


def persisted_row_values(row: NormalizedSourceRow) -> dict[str, object]:
    """Return only immutable-revision fields. Diagnostics never define identity."""

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
    }


def normalized_input_key(row: NormalizedSourceRow) -> str:
    """Generate a stable key without storing untrusted input payloads in progress rows."""

    encoded = json.dumps(
        persisted_row_values(row),
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "row:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _rejected_input_key(row_number: int, code: object) -> str:
    return f"rejected:{row_number}:{code}"
