from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from quakestrike.application.persistence import (
    EventTransactionResult,
    FeatureEventTransactionRequest,
)
from quakestrike.application.prediction_dispatch import (
    PredictionDispatch,
    process_feature_event_and_publish_prediction,
    publish_prediction_after_commit,
)
from quakestrike.infrastructure.queues.prediction_publisher import (
    PREDICTION_TASK_NAME,
    CeleryPredictionPublisher,
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


def test_publisher_runs_after_commit_for_new_work_only() -> None:
    publisher = RecordingPublisher([])
    correlation_id = uuid4()

    assert (
        publish_prediction_after_commit(
            _result(created=True),
            correlation_id=correlation_id,
            publisher=publisher,
        )
        is True
    )
    assert publisher.messages[0].correlation_id == correlation_id

    assert (
        publish_prediction_after_commit(
            _result(created=False),
            correlation_id=correlation_id,
            publisher=publisher,
        )
        is False
    )
    assert len(publisher.messages) == 1


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
    publisher = RecordingPublisher([])

    returned = process_feature_event_and_publish_prediction(
        RecordingTransactions(result), request, publisher
    )

    assert returned is result
    assert publisher.messages[0].correlation_id == request.correlation_id


class RecordingCeleryApp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def send_task(self, name: str, **kwargs: object) -> None:
        self.calls.append((name, kwargs))


def test_celery_adapter_sends_only_the_versioned_identifier_command() -> None:
    app = RecordingCeleryApp()
    publisher = CeleryPredictionPublisher(app)  # type: ignore[arg-type]
    dispatch = PredictionDispatch(uuid4(), uuid4(), uuid4())

    publisher.publish(dispatch)

    assert len(app.calls) == 1
    name, kwargs = app.calls[0]
    assert name == PREDICTION_TASK_NAME
    assert kwargs["queue"] == "prediction"
    assert kwargs["args"] == [
        {
            "message_version": 1,
            "dispatch_id": str(dispatch.dispatch_id),
            "job_id": str(dispatch.job_id),
            "correlation_id": str(dispatch.correlation_id),
        }
    ]


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
            publisher=publisher,
        )
        is False
    )
    assert publisher.messages == []
