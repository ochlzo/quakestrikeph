"""Versioned prediction queue consumer and runnable test-model worker."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from celery import Celery
from celery.exceptions import Reject
from pydantic import ValidationError

from quakestrike.application.prediction import ExecutePrediction, PredictionModel, PredictionStore
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.database.prediction import SqlAlchemyPredictionStore
from quakestrike.infrastructure.logging.json_logging import log_event, log_exception_event
from quakestrike.infrastructure.models.deterministic_test import DeterministicTestModel
from quakestrike.infrastructure.queues.celery_app import PREDICTION_QUEUE, create_celery_app
from quakestrike.infrastructure.queues.contracts import parse_prediction_command
from quakestrike.infrastructure.queues.prediction_publisher import PREDICTION_TASK_NAME
from quakestrike.infrastructure.settings import Settings
from quakestrike.runtime import run_service


def handle_prediction_command(
    payload: object,
    *,
    store: PredictionStore,
    model: PredictionModel,
    logger: logging.Logger,
) -> str:
    if not isinstance(payload, Mapping):
        return "rejected"
    try:
        command = parse_prediction_command(payload)
    except ValidationError:
        log_event(
            logger,
            logging.WARNING,
            "Prediction command is invalid.",
            event_code="prediction_command_invalid",
        )
        return "rejected"
    outcome = ExecutePrediction(store, model).execute(
        command.dispatch_id, command.job_id, command.correlation_id
    )
    if outcome == "stale":
        log_event(
            logger,
            logging.WARNING,
            "Prediction completion lost its processing lease.",
            event_code="prediction_completion_stale",
            context={"job_id": str(command.job_id)},
        )
    return outcome


def process_prediction_delivery(settings: Settings, payload: object) -> str:
    """Build database resources in the process that handles this delivery."""

    engine = create_database_engine(settings.database_url)
    try:
        return handle_prediction_command(
            payload,
            store=SqlAlchemyPredictionStore(create_session_factory(engine)),
            model=DeterministicTestModel(),
            logger=logging.getLogger("prediction-worker"),
        )
    finally:
        engine.dispose()


def create_prediction_app(
    settings: Settings, *, command_handler: Callable[[object], str] | None = None
) -> Celery:
    """Register the existing wire task name on the prediction queue."""

    app = create_celery_app(settings)
    handler = command_handler or (lambda payload: process_prediction_delivery(settings, payload))

    @app.task(
        name=PREDICTION_TASK_NAME,
        acks_late=True,
        reject_on_worker_lost=True,
        acks_on_failure_or_timeout=False,
    )
    def process_prediction(payload: object) -> str:
        try:
            return handler(payload)
        except Exception as error:
            log_exception_event(
                logging.getLogger("prediction-worker"),
                logging.ERROR,
                "Prediction command processing failed.",
                event_code="prediction_command_processing_failed",
                error=error,
            )
            raise Reject("Prediction command processing failed.", requeue=True) from None

    return app


def run_prediction(settings: Settings) -> int:
    """Consume the prediction queue with the deterministic issue #16 adapter."""

    app = create_prediction_app(settings)
    app.worker_main(
        [
            "worker",
            "--loglevel",
            settings.log_level,
            "--queues",
            PREDICTION_QUEUE,
            "--concurrency",
            "1",
            "--pool",
            "solo",
            "--hostname",
            "prediction-worker@%h",
        ]
    )
    return 0


def main() -> int:
    return run_service("prediction-worker", runtime=run_prediction)


if __name__ == "__main__":
    raise SystemExit(main())
