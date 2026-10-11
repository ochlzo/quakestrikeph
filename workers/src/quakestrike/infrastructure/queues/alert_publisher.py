"""Fixed Celery routing for identifier-only alert commands."""

from celery import Celery
from pydantic import ValidationError

from quakestrike.application.dispatch import AlertDispatch, DispatchPermanentError
from quakestrike.infrastructure.queues.celery_app import ALERT_QUEUE
from quakestrike.infrastructure.queues.contracts import AlertCommandV1

ALERT_TASK_NAME = "quakestrike.infrastructure.queues.tasks.publish_alert"


class CeleryAlertPublisher:
    def __init__(self, app: Celery) -> None:
        self._app = app

    def publish(self, dispatch: AlertDispatch) -> None:
        try:
            command = AlertCommandV1(
                dispatch_id=dispatch.dispatch_id,
                alert_job_id=dispatch.alert_job_id,
                correlation_id=dispatch.correlation_id,
            )
        except ValidationError as error:
            raise DispatchPermanentError("The alert identifiers are invalid.") from error
        self._app.send_task(ALERT_TASK_NAME, args=[command.to_message()], queue=ALERT_QUEUE)
