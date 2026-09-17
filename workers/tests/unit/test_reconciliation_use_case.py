from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from quakestrike.application.persistence import EventTransactionResult, RunCounters
from quakestrike.application.reconciliation import ReconcileCurrentCatalog
from quakestrike.domain.source_rows import CatalogParseResult, NormalizedSourceRow

NOW = datetime(2026, 9, 17, tzinfo=UTC)


class _Retriever:
    def __init__(self, parsed: CatalogParseResult) -> None:
        self.parsed = parsed

    def retrieve_current_catalog(self) -> CatalogParseResult:
        return self.parsed


class _Store:
    def __init__(self, *, exact_event_id: UUID | None = None, candidates=()) -> None:
        self.exact_event_id = exact_event_id
        self.candidates = candidates
        self.checkpoints: list[tuple[str, str, UUID | None]] = []
        self.requests = []

    def claim_run(self, *_args):
        return SimpleNamespace()

    def heartbeat_run(self, *_args) -> bool:
        return True

    def checkpoint_input(self, _run_id, _token, key, outcome, event_id) -> bool:
        self.checkpoints.append((key, outcome, event_id))
        return True

    def find_event_by_bulletin_id(self, _bulletin_id):
        return self.exact_event_id

    def find_group_candidates(self, _group_id):
        return self.candidates

    def process_event(self, request):
        self.requests.append(request)
        return EventTransactionResult(
            event_id=request.event_id,
            event_revision_id=request.revision.event_revision_id,
            revision_number=1,
            prediction_job_id=None,
            dispatch_id=None,
            event_created=self.exact_event_id is None,
            revision_created=True,
            prediction_created=False,
        )

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


def _execute(store: _Store, row: NormalizedSourceRow) -> _Store:
    values = iter(uuid4() for _ in range(20))
    result = ReconcileCurrentCatalog(
        store=store,
        retriever=_Retriever(CatalogParseResult((row,), ())),
        now=lambda: NOW,
        new_uuid=lambda: next(values),
    ).execute(uuid4())
    assert result.status == "succeeded"
    return store


def test_exact_bulletin_match_uses_existing_event_without_group_fallback() -> None:
    event_id = UUID("00000000-0000-0000-0000-000000000001")
    store = _execute(_Store(exact_event_id=event_id), _row())

    assert store.requests[0].event_id == event_id
    assert store.checkpoints[0][1] == "revised"


def test_new_bulletin_with_an_unmatched_group_creates_a_new_event() -> None:
    store = _execute(_Store(), _row())

    assert store.requests[0].event_id != UUID("00000000-0000-0000-0000-000000000000")
    assert store.checkpoints[0][1] == "inserted"


def test_source_less_row_cannot_create_an_event() -> None:
    store = _execute(_Store(), _row(bulletin=None, group=None))

    assert store.requests == []
    assert store.checkpoints[0][1:] == ("rejected", None)


def test_group_only_row_attaches_when_exactly_one_candidate_passes() -> None:
    event_id = UUID("00000000-0000-0000-0000-000000000001")
    candidate = SimpleNamespace(
        event_id=event_id,
        source_event_group_id="2025_0102_0304",
        latitude=Decimal("10"),
        longitude=Decimal("125"),
        magnitude=Decimal("4.2"),
    )
    store = _execute(_Store(candidates=(candidate,)), _row(bulletin=None))

    assert store.requests[0].event_id == event_id


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
    store = _execute(_Store(candidates=candidates), _row())

    assert store.requests == []
    assert store.checkpoints[0][1:] == ("rejected", None)
