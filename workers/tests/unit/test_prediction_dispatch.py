from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from quakestrike.application.dispatch import (
    DispatchClaim,
    DurableDispatcher,
    PredictionDispatch,
)
from quakestrike.application.persistence import FeatureEventTransactionRequest

NOW = datetime(2026, 9, 18, 2, 0, tzinfo=UTC)


@dataclass
class RecordingPublisher:
    messages: list[PredictionDispatch] = field(default_factory=list)

    def publish(self, dispatch: PredictionDispatch) -> None:
        self.messages.append(dispatch)


@dataclass
class RecordingStore:
    claims: tuple[DispatchClaim, ...]
    enqueued: list[DispatchClaim] = field(default_factory=list)
    retried: list[tuple[DispatchClaim, Exception]] = field(default_factory=list)

    def claim_due(self, limit: int, *, now: datetime) -> tuple[DispatchClaim, ...]:
        return self.claims

    def mark_enqueued(self, claim: DispatchClaim) -> None:
        self.enqueued.append(claim)

    def mark_retry(self, claim: DispatchClaim, error: Exception, *, now: datetime) -> str:
        self.retried.append((claim, error))
        return "retry_wait"


def _publishers(publisher: RecordingPublisher) -> dict[str, RecordingPublisher]:
    return {"ingestion": publisher, "prediction": publisher}


def test_feature_transaction_request_requires_one_correlation_id() -> None:
    with pytest.raises(TypeError, match="correlation_id"):
        FeatureEventTransactionRequest(
            event_id=uuid4(),
            ingestion_run_id=uuid4(),
            revision=object(),  # type: ignore[arg-type]
            model_release_id=uuid4(),
        )


def test_shared_dispatcher_records_prediction_acceptance_after_publishing() -> None:
    dispatch = PredictionDispatch(uuid4(), uuid4(), uuid4())
    store = RecordingStore((DispatchClaim(dispatch, uuid4()),))
    publisher = RecordingPublisher()

    result = DurableDispatcher(
        store,
        _publishers(publisher),
        batch_size=10,
        clock=lambda: NOW,
    ).dispatch_due()

    assert result.enqueued == 1
    assert publisher.messages == [dispatch]
    assert len(store.enqueued) == 1
    assert store.retried == []


def test_shared_dispatcher_records_retry_when_prediction_publication_fails() -> None:
    dispatch = PredictionDispatch(uuid4(), uuid4(), uuid4())
    store = RecordingStore((DispatchClaim(dispatch, uuid4()),))

    class FailingPublisher:
        def publish(self, dispatch: PredictionDispatch) -> None:
            raise RuntimeError("Redis unavailable")

    result = DurableDispatcher(
        store,
        {"ingestion": FailingPublisher(), "prediction": FailingPublisher()},
        batch_size=10,
        clock=lambda: NOW,
    ).dispatch_due()

    assert result.retry_wait == 1
    assert store.enqueued == []
    assert len(store.retried) == 1
