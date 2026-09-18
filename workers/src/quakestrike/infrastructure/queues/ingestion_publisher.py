"""Celery adapter for the IDs-only ingestion command."""

from __future__ import annotations

from celery import Celery
from pydantic import ValidationError

from quakestrike.application.dispatch import DispatchPermanentError, IngestionDispatch
from quakestrike.infrastructure.queues.celery_app import INGESTION_QUEUE, INGESTION_TASK_NAME
from quakestrike.infrastructure.queues.contracts import IngestionCommandV1


class CeleryIngestionPublisher:
    """Send a committed ingestion dispatch to the ingestion queue."""

    def __init__(self, app: Celery) -> None:
        self._app = app

    def publish(self, dispatch: IngestionDispatch) -> None:
        try:
            command = IngestionCommandV1(
                dispatch_id=dispatch.dispatch_id,
                run_id=dispatch.run_id,
                correlation_id=dispatch.correlation_id,
            )
        except ValidationError as error:
            raise DispatchPermanentError(
                "The ingestion dispatch identifiers are invalid."
            ) from error
        self._app.send_task(
            INGESTION_TASK_NAME,
            args=[command.to_message()],
            queue=INGESTION_QUEUE,
        )
