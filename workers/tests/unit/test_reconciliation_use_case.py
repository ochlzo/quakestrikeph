from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from quakestrike.application.persistence import (
    EventTransactionResult,
    FatalIdentityConflict,
    RunClaim,
    RunCounters,
)
from quakestrike.application.phivolcs import CatalogRetrievalLeaseLost
from quakestrike.application.reconciliation import (
    ReconcileCurrentCatalog,
    ReconciliationDiagnostic,
    coverage_for_anchor,
    merge_history_coverages,
)
from quakestrike.domain.features import HistoryCoverage
from quakestrike.domain.source_rows import (
    CatalogParseResult,
    NormalizedSourceRow,
)

NOW = datetime(2026, 9, 17, tzinfo=UTC)
CORRELATION_ID = UUID("00000000-0000-0000-0000-000000000002")
MODEL_RELEASE_ID = UUID("00000000-0000-0000-0000-000000000003")
HISTORY_COVERAGE = HistoryCoverage(NOW - timedelta(days=8), NOW, True)


def test_source_coverage_merge_preserves_outage_gap() -> None:
    first = HistoryCoverage(NOW - timedelta(days=9), NOW - timedelta(days=5), True)
    second = HistoryCoverage(NOW - timedelta(days=4), NOW, True)

    intervals = merge_history_coverages((first, second))

    assert len(intervals) == 2
    assert coverage_for_anchor(NOW - timedelta(days=4), intervals) == second


class _Retriever:
    def __init__(self, parsed: CatalogParseResult) -> None:
        self.parsed = parsed

    def retrieve_current_catalog(self, *, heartbeat=None) -> CatalogParseResult:
        if heartbeat is not None and not heartbeat():
            raise CatalogRetrievalLeaseLost()
        return self.parsed


class _Reporter:
    def __init__(self) -> None:
        self.diagnostics: list[ReconciliationDiagnostic] = []

    def report(self, diagnostic: ReconciliationDiagnostic) -> None:
        self.diagnostics.append(diagnostic)


class _Store:
    def __init__(self, *, exact_event_id: UUID | None = None, candidates=()) -> None:
        self.exact_event_id = exact_event_id
        self.candidates = candidates
        self.checkpoints: list[tuple[str, str, UUID | None]] = []
        self.requests = []
        self.heartbeats = 0
        self.heartbeat_times: list[datetime] = []
        self.claimed_at: datetime | None = None

    def successful_catalog_coverages(self, _start, _end):
        return ()

    def claim_run(self, run_id, token, now):
        self.claimed_at = now
        return RunClaim(
            run_id=run_id,
            worker_execution_id=token,
            correlation_id=CORRELATION_ID,
            attempt_count=1,
            trigger_type="manual",
        )

    def heartbeat_run(self, _run_id, _token, now) -> bool:
        self.heartbeats += 1
        self.heartbeat_times.append(now)
        return True

    def checkpoint_input(self, _run_id, _token, key, outcome, event_id) -> bool:
        self.checkpoints.append((key, outcome, event_id))
        return True

    def input_checkpoint_exists(self, _run_id, key) -> bool:
        return any(checkpoint[0] == key for checkpoint in self.checkpoints)

    def find_event_by_bulletin_id(self, _bulletin_id):
        return self.exact_event_id

    def find_group_candidates(self, _group_id):
        return self.candidates

    def process_event_with_features(self, request):
        self.requests.append(request)
        result = EventTransactionResult(
            event_id=request.event_id,
            event_revision_id=request.revision.event_revision_id,
            revision_number=1,
            prediction_job_id=None,
            dispatch_id=None,
            event_created=self.exact_event_id is None,
            revision_created=True,
            prediction_created=False,
        )
        outcome = (
            "inserted"
            if result.event_created
            else "revised"
            if result.revision_created
            else "unchanged"
        )
        self.checkpoint_input(None, None, request.input_key, outcome, result.event_id)
        return result

    def counters_for_run(self, *_args):
        return RunCounters(1, 1, 0, 0, 0)

    def complete_run(self, *_args) -> bool:
        return True

    def fail_run(self, *_args, **_kwargs):
        raise AssertionError("test did not expect a run-level failure")


def _row(*, bulletin="2025_0102_0304_B1", group="2025_0102_0304") -> NormalizedSourceRow:
    return NormalizedSourceRow.from_catalog_values(
        occurred_at=datetime(2025, 1, 2, 11, 4, tzinfo=ZoneInfo("Asia/Manila")),
        latitude="10",
        longitude="125",
        depth_km="7",
        magnitude="4.2",
        location_description="Test location",
        source_bulletin_id=bulletin,
        source_event_group_id=group,
        source_url="https://earthquake.phivolcs.dost.gov.ph/bulletin.html",
    )


def _execute(store: _Store, row: NormalizedSourceRow, reporter: _Reporter | None = None) -> _Store:
    values = iter(uuid4() for _ in range(20))
    result = ReconcileCurrentCatalog(
        store=store,
        retriever=_Retriever(CatalogParseResult((row,), ())),
        diagnostic_reporter=reporter or _Reporter(),
        model_release_id=MODEL_RELEASE_ID,
        history_coverage=HISTORY_COVERAGE,
        now=lambda: NOW,
        new_uuid=lambda: next(values),
    ).execute(uuid4())
    assert result.status == "succeeded"
    return store


def test_source_less_row_cannot_create_an_event() -> None:
    reporter = _Reporter()
    store = _execute(_Store(), _row(bulletin=None, group=None), reporter)

    assert store.requests == []
    assert store.checkpoints[0][1:] == ("rejected", None)
    assert [item.code for item in reporter.diagnostics] == ["MISSING_SOURCE_ID"]


def test_group_only_row_attaches_when_exactly_one_candidate_passes() -> None:
    event_id = UUID("00000000-0000-0000-0000-000000000001")
    candidate = SimpleNamespace(
        event_id=event_id,
        source_event_group_id="2025_0102_0304",
        latitude=Decimal("10.25"),
        longitude=Decimal("124.75"),
        magnitude=Decimal("5.2"),
    )
    reporter = _Reporter()
    store = _execute(_Store(candidates=(candidate,)), _row(bulletin=None), reporter)

    assert store.requests[0].event_id == event_id
    assert reporter.diagnostics == []


def test_ambiguous_group_fallback_rejects_the_row() -> None:
    candidates = tuple(
        SimpleNamespace(
            event_id=uuid4(),
            source_event_group_id="2025_0102_0304",
            latitude=Decimal("10"),
            longitude=Decimal("125"),
            magnitude=Decimal("4.2"),
        )
        for _ in range(2)
    )
    reporter = _Reporter()
    store = _execute(_Store(candidates=candidates), _row(), reporter)

    assert store.requests == []
    assert store.checkpoints[0][1:] == ("rejected", None)
    assert [item.code for item in reporter.diagnostics] == ["AMBIGUOUS_FALLBACK"]


def test_retrieval_heartbeats_before_row_processing_and_stops_on_a_lost_lease() -> None:
    store = _Store()
    values = iter(uuid4() for _ in range(20))
    moments = iter(
        (
            NOW,
            NOW + timedelta(minutes=14),
            NOW + timedelta(minutes=28),
            NOW + timedelta(minutes=29),
            NOW + timedelta(minutes=30),
        )
    )

    class _LongRetriever:
        def retrieve_current_catalog(self, *, heartbeat):
            assert heartbeat() is True
            assert heartbeat() is True
            return CatalogParseResult((_row(),), ())

    result = ReconcileCurrentCatalog(
        store=store,
        retriever=_LongRetriever(),
        diagnostic_reporter=_Reporter(),
        model_release_id=MODEL_RELEASE_ID,
        now=lambda: next(moments),
        new_uuid=lambda: next(values),
    ).execute(uuid4())

    assert result.status == "succeeded"
    assert store.heartbeats >= 3
    assert store.claimed_at is not None
    assert max(store.heartbeat_times) - store.claimed_at > timedelta(minutes=15)


def test_lost_lease_during_retrieval_does_not_process_rows() -> None:
    store = _Store()

    class _LeaseLosingRetriever:
        def retrieve_current_catalog(self, *, heartbeat):
            assert heartbeat() is True
            raise CatalogRetrievalLeaseLost()

    result = ReconcileCurrentCatalog(
        store=store,
        retriever=_LeaseLosingRetriever(),
        diagnostic_reporter=_Reporter(),
        model_release_id=MODEL_RELEASE_ID,
        now=lambda: NOW,
    ).execute(uuid4())

    assert result.status == "lease_lost"
    assert store.requests == []


def test_unexpected_persistence_error_uses_a_safe_retry_transition() -> None:
    class _FailingStore(_Store):
        def process_event_with_features(self, _request):
            raise RuntimeError("database password leaked")

        def fail_run(self, *_args, **_kwargs):
            self.failure = (_args, _kwargs)
            return "retry_wait"

    store = _FailingStore()
    result = ReconcileCurrentCatalog(
        store=store,
        retriever=_Retriever(CatalogParseResult((_row(),), ())),
        diagnostic_reporter=_Reporter(),
        model_release_id=MODEL_RELEASE_ID,
        now=lambda: NOW,
    ).execute(uuid4())

    assert result.status == "retry_wait"
    assert store.checkpoints == []
    assert store.failure[0][3] == "RECONCILIATION_PERSISTENCE_FAILURE"
    assert "password" not in store.failure[0][4]


def test_fatal_identity_conflict_fails_the_run_with_a_safe_terminal_error() -> None:
    class _IdentityConflictStore(_Store):
        def process_event_with_features(self, _request):
            raise FatalIdentityConflict("mapped event id and secret payload disagree")

        def fail_run(self, *_args, **_kwargs):
            self.failure = (_args, _kwargs)
            return "failed"

    store = _IdentityConflictStore()
    result = ReconcileCurrentCatalog(
        store=store,
        retriever=_Retriever(CatalogParseResult((_row(),), ())),
        diagnostic_reporter=_Reporter(),
        model_release_id=MODEL_RELEASE_ID,
        now=lambda: NOW,
    ).execute(uuid4())

    assert result.status == "failed"
    assert store.failure[0][3] == "BULLETIN_EVENT_IDENTITY_CONFLICT"
    assert store.failure[1]["retryable"] is False
    assert "secret" not in store.failure[0][4]
