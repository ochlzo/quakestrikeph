from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from quakestrike.application.dispatch import (
    DispatchBatchResult,
    DispatchClaim,
    DispatchOutcome,
    DispatchPermanentError,
    DurableDispatcher,
    IngestionDispatch,
    PredictionDispatch,
)

NOW = datetime(2026, 9, 18, 2, 0, tzinfo=UTC)


@dataclass
class RecordingStore:
    claims: tuple[DispatchClaim, ...]
    events: list[tuple[str, object]] = field(default_factory=list)
    calls: list[tuple[int, datetime]] = field(default_factory=list)
    retry_times: list[datetime] = field(default_factory=list)

    def claim_due(self, limit: int, *, now: datetime) -> tuple[DispatchClaim, ...]:
        self.calls.append((limit, now))
        return self.claims

    def mark_enqueued(self, claim: DispatchClaim) -> None:
        self.events.append(("enqueued", claim))

    def mark_retry(self, claim: DispatchClaim, error: Exception, *, now: datetime) -> str:
        self.retry_times.append(now)
        self.events.append(("retry_wait", claim))
        return "retry_wait"

    def mark_stopped(self, claim: DispatchClaim, error: Exception, *, now: datetime) -> None:
        self.events.append(("stopped", claim))


@dataclass
class RecordingPublisher:
    messages: list[object] = field(default_factory=list)
    events: list[tuple[str, object]] = field(default_factory=list)

    def publish(self, dispatch: object) -> None:
        self.messages.append(dispatch)
        self.events.append(("published", dispatch))


def test_shared_dispatcher_routes_both_target_kinds_in_one_bounded_scan() -> None:
    ingestion = IngestionDispatch(uuid4(), uuid4(), uuid4())
    prediction = PredictionDispatch(uuid4(), uuid4(), uuid4())
    claims = (
        DispatchClaim(ingestion, uuid4()),
        DispatchClaim(prediction, uuid4()),
    )
    store = RecordingStore(claims)
    ingestion_publisher = RecordingPublisher(events=store.events)
    prediction_publisher = RecordingPublisher(events=store.events)

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
    assert store.events == [
        ("published", ingestion),
        ("enqueued", claims[0]),
        ("published", prediction),
        ("enqueued", claims[1]),
    ]
    assert result.target_counts_for("ingestion").enqueued == 1
    assert result.target_counts_for("prediction").enqueued == 1
    assert result.outcomes == (
        DispatchOutcome(ingestion, "enqueued"),
        DispatchOutcome(prediction, "enqueued"),
    )


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
    assert result.outcomes[0].dispatch == prediction
    assert result.outcomes[0].status == "stopped"
    assert isinstance(result.outcomes[0].error, DispatchPermanentError)


def test_shared_dispatcher_retries_nonpermanent_errors_and_continues_after_failure() -> None:
    prediction = PredictionDispatch(uuid4(), uuid4(), uuid4())
    ingestion = IngestionDispatch(uuid4(), uuid4(), uuid4())
    claims = (DispatchClaim(prediction, uuid4()), DispatchClaim(ingestion, uuid4()))
    store = RecordingStore(claims)
    error = ValueError("publisher failed")

    class FailingPublisher:
        def publish(self, dispatch: object) -> None:
            raise error

    ingestion_publisher = RecordingPublisher(events=store.events)
    clock_values = iter((NOW, NOW + timedelta(seconds=31)))
    result = DurableDispatcher(
        store,
        {"ingestion": ingestion_publisher, "prediction": FailingPublisher()},
        batch_size=10,
        clock=lambda: next(clock_values),
    ).dispatch_due()

    assert result == DispatchBatchResult(claimed=2, enqueued=1, retry_wait=1, stopped=0)
    assert store.calls == [(10, NOW)]
    assert store.events == [
        ("retry_wait", claims[0]),
        ("published", ingestion),
        ("enqueued", claims[1]),
    ]
    assert store.retry_times == [NOW + timedelta(seconds=31)]
    assert ingestion_publisher.messages == [ingestion]
    assert result.target_counts_for("prediction").retry_wait == 1
    assert result.target_counts_for("ingestion").enqueued == 1
    assert result.outcomes == (
        DispatchOutcome(prediction, "retry_wait", error),
        DispatchOutcome(ingestion, "enqueued"),
    )
    assert result.outcomes[0].error is error


def test_dispatcher_rejects_a_batch_above_ten() -> None:
    with pytest.raises(ValueError, match="between 1 and 10"):
        DurableDispatcher(RecordingStore(()), RecordingPublisher(), batch_size=11)
