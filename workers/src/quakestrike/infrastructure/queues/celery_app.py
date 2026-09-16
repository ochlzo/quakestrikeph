"""Celery configuration for the future worker processes."""

from __future__ import annotations

from celery import Celery

from quakestrike.infrastructure.settings import Settings

INGESTION_QUEUE = "ingestion"
PREDICTION_QUEUE = "prediction"


def create_celery_app(settings: Settings) -> Celery:
    """Create a Celery app with the accepted queue and acknowledgement rules."""

    app = Celery("quakestrike", broker=settings.redis_url)
    app.conf.update(
        task_default_queue=INGESTION_QUEUE,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_ignore_result=True,
        worker_concurrency=settings.ingestor_concurrency,
        worker_prefetch_multiplier=1,
        task_routes={
            "quakestrike.data_ingestor.worker.process_ingestion": {
                "queue": INGESTION_QUEUE,
            },
            "quakestrike.infrastructure.queues.tasks.publish_prediction": {
                "queue": PREDICTION_QUEUE,
            },
        },
        quakestrike_poll_interval_seconds=settings.poll_interval_seconds,
        beat_schedule={},
    )
    return app
