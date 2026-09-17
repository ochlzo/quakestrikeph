from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from quakestrike.application.ingestion_dispatch import (
    DispatchBatchResult,
    DurableIngestionDispatcher,
    IngestionDispatch,
    IngestionDispatchClaim,
)

NOW = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)


def _dispatch(value: int) -> IngestionDispatch:
    return IngestionDispatch(
        dispatch_id=UUID(f"00000000-0000-0000-0000-0000000001{value:02d}"),
        run_id=UUID(f"00000000-0000-0000-0000-0000000002{value:02d}"),
        correlation_id=UUID(f"00000000-0000-0000-0000-0000000003{value:02d}"),
    )


@dataclass
class RecordingStore:
    claims: tuple[IngestionDispatchClaim, ...]
    events: list[tuple[str, IngestionDispatch]] = field(default_factory=list)
    limits: list[tuple[int, datetime]] = field(default_factory=list)
    retry_times: list[datetime] = field(default_factory=list)
    retry_states: list[str] = field(default_factory=list)

    def claim_due(self, limit: int, *, now: datetime) -> tuple[IngestionDispatchClaim, ...]:
        self.limits.append((limit, now))
        return self.claims

    def mark_enqueued(self, claim: IngestionDispatchClaim) -> None:
        self.events.append(("enqueued", claim.dispatch))

    def mark_retry(self, claim, error, *, now):  # type: ignore[no-untyped-def]
        self.retry_times.append(now)
        self.events.append(("retry_wait", claim.dispatch))
        return self.retry_states.pop(0)


@dataclass
class RecordingPublisher:
    events: list[tuple[str, IngestionDispatch]]

    def publish(self, dispatch: IngestionDispatch) -> None:
        self.events.append(("published", dispatch))


class FailFirstPublisher:
    def __init__(self, events: list[tuple[str, IngestionDispatch]]) -> None:
        self._events = events
        self._failed = False

    def publish(self, dispatch: IngestionDispatch) -> None:
        if not self._failed:
            self._failed = True
            raise RuntimeError("Redis unavailable")
        self._events.append(("published", dispatch))


def test_dispatcher_rejects_a_batch_above_ten() -> None:
    with pytest.raises(ValueError, match="between 1 and 10"):
        DurableIngestionDispatcher(
            RecordingStore(()),
            RecordingPublisher([]),
            batch_size=11,
        )


def test_dispatcher_claims_a_bounded_batch_and_acknowledges_after_publish() -> None:
    first = _dispatch(1)
    second = _dispatch(2)
    claims = (
        IngestionDispatchClaim(dispatch=first, token=UUID(int=401)),
        IngestionDispatchClaim(dispatch=second, token=UUID(int=402)),
    )
    store = RecordingStore(claims)
    events: list[tuple[str, IngestionDispatch]] = []
    publisher = RecordingPublisher(events)
    store.events = events

    result = DurableIngestionDispatcher(
        store,
        publisher,
        batch_size=10,
        clock=lambda: NOW,
    ).dispatch_due()

    assert result == DispatchBatchResult(claimed=2, enqueued=2, retry_wait=0, stopped=0)
    assert store.limits == [(10, NOW)]
    assert events == [
        ("published", first),
        ("enqueued", first),
        ("published", second),
        ("enqueued", second),
    ]


def test_dispatcher_records_retry_and_continues_after_publish_failure() -> None:
    first = _dispatch(3)
    second = _dispatch(4)
    events: list[tuple[str, IngestionDispatch]] = []
    store = RecordingStore(
        claims=(
            IngestionDispatchClaim(dispatch=first, token=UUID(int=403)),
            IngestionDispatchClaim(dispatch=second, token=UUID(int=404)),
        ),
        events=events,
        retry_states=["retry_wait"],
    )

    clock_values = iter((NOW, NOW + timedelta(seconds=31)))
    result = DurableIngestionDispatcher(
        store,
        FailFirstPublisher(events),
        batch_size=10,
        clock=lambda: next(clock_values),
    ).dispatch_due()

    assert result == DispatchBatchResult(claimed=2, enqueued=1, retry_wait=1, stopped=0)
    assert events == [
        ("retry_wait", first),
        ("published", second),
        ("enqueued", second),
    ]
    assert store.retry_times == [NOW + timedelta(seconds=31)]
