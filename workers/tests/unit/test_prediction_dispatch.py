from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from quakestrike.application.persistence import (
    EventTransactionResult,
    FeatureEventTransactionRequest,
)
from quakestrike.application.prediction_dispatch import (
    DurablePredictionDispatcher,
    PredictionDispatch,
    PredictionDispatchClaim,
    process_feature_event_and_publish_prediction,
    publish_prediction_after_commit,
)


@dataclass
class RecordingPublisher:
    messages: list[PredictionDispatch]

    def publish(self, dispatch: PredictionDispatch) -> None:
        self.messages.append(dispatch)


def _result(*, created: bool) -> EventTransactionResult:
    return EventTransactionResult(
        event_id=uuid4(),
        event_revision_id=uuid4(),
        revision_number=1,
        prediction_job_id=uuid4() if created else None,
        dispatch_id=uuid4() if created else None,
        event_created=True,
        revision_created=True,
        prediction_created=created,
    )


def test_feature_transaction_request_requires_one_correlation_id() -> None:
    with pytest.raises(TypeError, match="correlation_id"):
        FeatureEventTransactionRequest(
            event_id=uuid4(),
            ingestion_run_id=uuid4(),
            revision=object(),  # type: ignore[arg-type]
            model_release_id=uuid4(),
        )


def test_publisher_runs_after_commit_for_new_work_only() -> None:
    dispatcher = RecordingDispatcher([])
    correlation_id = uuid4()

    assert (
        publish_prediction_after_commit(
            _result(created=True),
            correlation_id=correlation_id,
            dispatcher=dispatcher,
        )
        is True
    )
    assert dispatcher.messages[0].correlation_id == correlation_id

    assert (
        publish_prediction_after_commit(
            _result(created=False),
            correlation_id=correlation_id,
            dispatcher=dispatcher,
        )
        is False
    )
    assert len(dispatcher.messages) == 1


class RecordingTransactions:
    def __init__(self, result: EventTransactionResult) -> None:
        self.result = result

    def process_event_with_features(self, request: FeatureEventTransactionRequest):
        return self.result


def test_application_flow_publishes_only_after_transaction_returns() -> None:
    result = _result(created=True)
    request = FeatureEventTransactionRequest(
        event_id=uuid4(),
        ingestion_run_id=uuid4(),
        revision=object(),  # type: ignore[arg-type]
        model_release_id=uuid4(),
        correlation_id=uuid4(),
    )
    dispatcher = RecordingDispatcher([])

    returned = process_feature_event_and_publish_prediction(
        RecordingTransactions(result), request, dispatcher
    )

    assert returned is result
    assert dispatcher.messages[0].correlation_id == request.correlation_id


def test_no_prediction_ids_means_no_publish() -> None:
    publisher = RecordingPublisher([])
    result = EventTransactionResult(
        event_id=uuid4(),
        event_revision_id=uuid4(),
        revision_number=1,
        prediction_job_id=None,
        dispatch_id=None,
        event_created=True,
        revision_created=True,
        prediction_created=True,
    )

    assert (
        publish_prediction_after_commit(
            result,
            correlation_id=uuid4(),
            dispatcher=publisher,
        )
        is False
    )
    assert publisher.messages == []


@dataclass
class RecordingDispatcher:
    messages: list[PredictionDispatch]

    def dispatch(self, dispatch: PredictionDispatch) -> bool:
        self.messages.append(dispatch)
        return True


@dataclass
class RecordingDispatchStore:
    claims: list[PredictionDispatchClaim] = field(default_factory=list)
    enqueued: list[PredictionDispatchClaim] = field(default_factory=list)
    retried: list[tuple[PredictionDispatchClaim, Exception]] = field(default_factory=list)

    def claim(self, dispatch: PredictionDispatch) -> PredictionDispatchClaim:
        claim = PredictionDispatchClaim(dispatch=dispatch, token=uuid4())
        self.claims.append(claim)
        return claim

    def mark_enqueued(self, claim: PredictionDispatchClaim) -> None:
        self.enqueued.append(claim)

    def mark_retry(self, claim: PredictionDispatchClaim, error: Exception) -> None:
        self.retried.append((claim, error))


def test_durable_dispatcher_records_acceptance_after_publishing() -> None:
    store = RecordingDispatchStore()
    publisher = RecordingPublisher([])
    dispatcher = DurablePredictionDispatcher(store, publisher)
    dispatch = PredictionDispatch(uuid4(), uuid4(), uuid4())

    assert dispatcher.dispatch(dispatch) is True
    assert publisher.messages == [dispatch]
    assert len(store.enqueued) == 1
    assert store.retried == []


def test_durable_dispatcher_records_retry_when_queue_publish_fails() -> None:
    store = RecordingDispatchStore()

    class FailingPublisher:
        def publish(self, dispatch: PredictionDispatch) -> None:
            raise RuntimeError("Redis unavailable")

    dispatcher = DurablePredictionDispatcher(store, FailingPublisher())
    dispatch = PredictionDispatch(uuid4(), uuid4(), uuid4())

    with pytest.raises(RuntimeError, match="Redis unavailable"):
        dispatcher.dispatch(dispatch)

    assert store.enqueued == []
    assert len(store.retried) == 1
