"""Versioned prediction queue consumer and SEIS worker."""

from __future__ import annotations

import logging
import os
import socket
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
from quakestrike.infrastructure.models.seis import SeisModel
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
    context = {
        "worker": socket.gethostname(),
        "dispatch_id": str(command.dispatch_id),
        "job_id": str(command.job_id),
        "correlation_id": str(command.correlation_id),
    }
    attempt_context: dict[str, str] = {}

    def record_claim(claim):
        attempt_context["attempt_id"] = str(claim.attempt_id)
        log_event(
            logger,
            logging.INFO,
            "Prediction attempt claimed.",
            event_code="prediction_attempt_claimed",
            context=context | attempt_context,
        )

    outcome = ExecutePrediction(
        store,
        model,
        on_claim=record_claim,
    ).execute(command.dispatch_id, command.job_id, command.correlation_id)
    log_event(
        logger,
        logging.INFO,
        "Prediction command processed.",
        event_code="prediction_command_processed",
        context=context | attempt_context | {"status": outcome},
    )
    if outcome == "stale":
        log_event(
            logger,
            logging.WARNING,
            "Prediction completion lost its processing lease.",
            event_code="prediction_completion_stale",
            context=context,
        )
    return outcome


def process_prediction_delivery(settings: Settings, payload: object, model: PredictionModel) -> str:
    """Build database resources in the process that handles this delivery."""

    engine = create_database_engine(settings.database_url)
    try:
        return handle_prediction_command(
            payload,
            store=SqlAlchemyPredictionStore(
                create_session_factory(engine), configured_release_id=settings.model_release_id
            ),
            model=model,
            logger=logging.getLogger("prediction-worker"),
        )
    finally:
        engine.dispose()


def create_prediction_app(
    settings: Settings, *, command_handler: Callable[[object], str]
) -> Celery:
    """Register the existing wire task name on the prediction queue."""

    app = create_celery_app(settings)

    @app.task(
        name=PREDICTION_TASK_NAME,
        acks_late=True,
        reject_on_worker_lost=True,
        acks_on_failure_or_timeout=False,
        soft_time_limit=settings.prediction_soft_time_limit_seconds,
        time_limit=settings.prediction_hard_time_limit_seconds,
    )
    def process_prediction(payload: object) -> str:
        try:
            return command_handler(payload)
        except Exception as error:
            context = {"worker": socket.gethostname()}
            if isinstance(payload, Mapping):
                try:
                    command = parse_prediction_command(payload)
                except ValidationError:
                    pass
                else:
                    context.update(
                        dispatch_id=str(command.dispatch_id),
                        job_id=str(command.job_id),
                        correlation_id=str(command.correlation_id),
                    )
            log_exception_event(
                logging.getLogger("prediction-worker"),
                logging.ERROR,
                "Prediction command processing failed.",
                event_code="prediction_command_processing_failed",
                error=error,
                context=context,
            )
            raise Reject("Prediction command processing failed.", requeue=True) from None

    return app


def run_prediction(
    settings: Settings,
    *,
    model: PredictionModel | None = None,
    hostname: str = "prediction-worker@%h",
) -> int:
    """Load SEIS before consuming work, with a supplied adapter for isolated tests."""

    selected_model = model or SeisModel(
        settings.model_artifact_directory, settings.model_release_id
    )

    def handle(payload: object) -> str:
        if isinstance(selected_model, SeisModel):
            try:
                selected_model.verify_artifacts()
            except (OSError, ValueError):
                log_event(
                    logging.getLogger("prediction-worker"),
                    logging.ERROR,
                    "Model artifacts changed; stopping before a prediction claim.",
                    event_code="prediction_artifacts_unhealthy",
                )
                os._exit(2)
        return process_prediction_delivery(settings, payload, selected_model)

    app = create_prediction_app(settings, command_handler=handle)
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
            "prefork",
            "--hostname",
            hostname,
        ]
    )
    return 0


def main() -> int:
    return run_service("prediction-worker", runtime=run_prediction)


if __name__ == "__main__":
    raise SystemExit(main())
