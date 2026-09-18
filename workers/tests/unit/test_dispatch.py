from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from quakestrike.application.dispatch import (
    DispatchBatchResult,
    DispatchClaim,
    DispatchPermanentError,
    DurableDispatcher,
    IngestionDispatch,
    PredictionDispatch,
)

NOW = datetime(2026, 9, 18, 2, 0, tzinfo=UTC)


@dataclass
class RecordingStore:
    claims: tuple[DispatchClaim, ...]
    events: list[tuple[str, DispatchClaim]] = field(default_factory=list)
    calls: list[tuple[int, datetime]] = field(default_factory=list)

    def claim_due(self, limit: int, *, now: datetime) -> tuple[DispatchClaim, ...]:
        self.calls.append((limit, now))
        return self.claims

    def mark_enqueued(self, claim: DispatchClaim) -> None:
        self.events.append(("enqueued", claim))

    def mark_retry(self, claim: DispatchClaim, error: Exception, *, now: datetime) -> str:
        self.events.append(("retry_wait", claim))
        return "retry_wait"

    def mark_stopped(self, claim: DispatchClaim, error: Exception, *, now: datetime) -> None:
        self.events.append(("stopped", claim))


@dataclass
class RecordingPublisher:
    messages: list[object] = field(default_factory=list)

    def publish(self, dispatch: object) -> None:
        self.messages.append(dispatch)


def test_shared_dispatcher_routes_both_target_kinds_in_one_bounded_scan() -> None:
    ingestion = IngestionDispatch(uuid4(), uuid4(), uuid4())
    prediction = PredictionDispatch(uuid4(), uuid4(), uuid4())
    claims = (
        DispatchClaim(ingestion, uuid4()),
        DispatchClaim(prediction, uuid4()),
    )
    store = RecordingStore(claims)
    ingestion_publisher = RecordingPublisher()
    prediction_publisher = RecordingPublisher()

    result = DurableDispatcher(
        store,
        {
            "ingestion": ingestion_publisher,
            "prediction": prediction_publisher,
        },
        batch_size=10,
        clock=lambda: NOW,
    ).dispatch_due()

    assert result == DispatchBatchResult(claimed=2, enqueued=2, retry_wait=0, stopped=0)
    assert store.calls == [(10, NOW)]
    assert ingestion_publisher.messages == [ingestion]
    assert prediction_publisher.messages == [prediction]
    assert [event[0] for event in store.events] == ["enqueued", "enqueued"]
    assert result.target_counts_for("ingestion").enqueued == 1
    assert result.target_counts_for("prediction").enqueued == 1


def test_shared_dispatcher_stops_a_permanently_invalid_command() -> None:
    prediction = PredictionDispatch(uuid4(), uuid4(), uuid4())
    store = RecordingStore((DispatchClaim(prediction, uuid4()),))

    class InvalidPublisher:
        def publish(self, dispatch: object) -> None:
            raise DispatchPermanentError("invalid command")

    result = DurableDispatcher(
        store,
        {"ingestion": InvalidPublisher(), "prediction": InvalidPublisher()},
        batch_size=10,
        clock=lambda: NOW,
    ).dispatch_due()

    assert result == DispatchBatchResult(claimed=1, enqueued=0, retry_wait=0, stopped=1)
    assert store.events == [("stopped", store.claims[0])]


@pytest.mark.parametrize(
    "error", [TypeError("publisher call failed"), ValueError("publisher failed")]
)
def test_shared_dispatcher_retries_nonpermanent_publisher_errors(error: Exception) -> None:
    prediction = PredictionDispatch(uuid4(), uuid4(), uuid4())
    store = RecordingStore((DispatchClaim(prediction, uuid4()),))

    class FailingPublisher:
        def publish(self, dispatch: object) -> None:
            raise error

    result = DurableDispatcher(
        store,
        {"ingestion": FailingPublisher(), "prediction": FailingPublisher()},
        batch_size=10,
        clock=lambda: NOW,
    ).dispatch_due()

    assert result == DispatchBatchResult(claimed=1, enqueued=0, retry_wait=1, stopped=0)
    assert store.events == [("retry_wait", store.claims[0])]
