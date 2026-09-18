"""Celery adapter for the IDs-only prediction command."""

from __future__ import annotations

from celery import Celery
from pydantic import ValidationError

from quakestrike.application.dispatch import DispatchPermanentError, PredictionDispatch
from quakestrike.infrastructure.queues.celery_app import PREDICTION_QUEUE
from quakestrike.infrastructure.queues.contracts import PredictionCommandV1

PREDICTION_TASK_NAME = "quakestrike.infrastructure.queues.tasks.publish_prediction"


class CeleryPredictionPublisher:
    """Send a committed prediction dispatch to the separate prediction queue."""

    def __init__(self, app: Celery) -> None:
        self._app = app

    def publish(self, dispatch: PredictionDispatch) -> None:
        try:
            command = PredictionCommandV1(
                dispatch_id=dispatch.dispatch_id,
                job_id=dispatch.job_id,
                correlation_id=dispatch.correlation_id,
            )
        except ValidationError as error:
            raise DispatchPermanentError(
                "The prediction dispatch identifiers are invalid."
            ) from error
        self._app.send_task(
            PREDICTION_TASK_NAME,
            args=[command.to_message()],
            queue=PREDICTION_QUEUE,
        )
