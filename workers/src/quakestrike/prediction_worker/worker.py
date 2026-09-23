"""Versioned prediction queue consumer; model execution is injected."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Protocol

from celery import Celery
from pydantic import ValidationError

from quakestrike.domain.prediction import InvalidPredictionOutput, compose_forecast
from quakestrike.infrastructure.database.prediction import (
    SqlAlchemyPredictionStore,
    StalePredictionAttempt,
)
from quakestrike.infrastructure.logging.json_logging import log_event
from quakestrike.infrastructure.queues.celery_app import create_celery_app
from quakestrike.infrastructure.queues.contracts import parse_prediction_command
from quakestrike.infrastructure.queues.prediction_publisher import PREDICTION_TASK_NAME
from quakestrike.infrastructure.settings import Settings


class PredictionModel(Protocol):
    def predict(self, features: Mapping[str, object]) -> Mapping[str, object]: ...


def handle_prediction_command(
    payload: object,
    *,
    store: SqlAlchemyPredictionStore,
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
    claim = store.claim(command.dispatch_id, command.job_id, command.correlation_id)
    if claim is None:
        return "unclaimed"
    try:
        try:
            output = compose_forecast(model.predict(claim.features), claim.event_time)
        except InvalidPredictionOutput:
            store.fail(claim, "invalid_output", "The model output violates the forecast contract.")
            return "failed"
        except Exception:
            store.fail(claim, "model_runtime_error", "The prediction model could not finish.")
            return "failed"
        return "succeeded" if store.complete(claim, output) is not None else "failed"
    except StalePredictionAttempt:
        log_event(
            logger,
            logging.WARNING,
            "Prediction completion lost its processing lease.",
            event_code="prediction_completion_stale",
            context={"job_id": str(command.job_id)},
        )
        return "stale"


def create_prediction_app(
    settings: Settings,
    *,
    store: SqlAlchemyPredictionStore,
    model: PredictionModel,
) -> Celery:
    """Register the existing wire task name on the prediction queue."""

    app = create_celery_app(settings)

    @app.task(name=PREDICTION_TASK_NAME, acks_late=True, reject_on_worker_lost=True)
    def process_prediction(payload: object) -> str:
        return handle_prediction_command(
            payload, store=store, model=model, logger=logging.getLogger("prediction-worker")
        )

    return app
