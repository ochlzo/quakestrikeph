"""Celery configuration for the future worker processes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from celery import Celery
from celery.schedules import schedstate, schedule

from quakestrike.infrastructure.settings import Settings

INGESTION_QUEUE = "ingestion"
PREDICTION_QUEUE = "prediction"
INGESTION_TASK_NAME = "quakestrike.data_ingestor.worker.process_ingestion"
DURABLE_INGESTION_TICK = "quakestrike.scheduler.beat.durable_ingestion_tick"


class UtcBoundarySchedule(schedule):
    """Run only at future UTC epoch-aligned boundaries, with no startup tick."""

    def __init__(self, interval_seconds: int, **kwargs: object) -> None:
        super().__init__(run_every=interval_seconds, **kwargs)
        self.interval_seconds = interval_seconds

    def is_due(self, last_run_at: datetime) -> schedstate:
        now = self.now().astimezone(UTC).timestamp()
        boundary = int(now // self.interval_seconds) * self.interval_seconds
        next_boundary = boundary + self.interval_seconds
        due = boundary > last_run_at.astimezone(UTC).timestamp()
        return schedstate(due, self.interval_seconds if due else max(0, next_boundary - now))


def create_celery_app(
    settings: Settings,
    *,
    ingestion_tick: Callable[[], object] | None = None,
) -> Celery:
    """Create a Celery app with queue rules and one local durable polling schedule."""

    app = Celery("quakestrike", broker=settings.redis_url)
    configuration: dict[str, object] = {
        "task_default_queue": INGESTION_QUEUE,
        "task_acks_late": True,
        "task_reject_on_worker_lost": True,
        "task_ignore_result": True,
        "result_expires": None,
        "worker_concurrency": settings.ingestor_concurrency,
        "worker_prefetch_multiplier": 1,
        "task_routes": {
            INGESTION_TASK_NAME: {
                "queue": INGESTION_QUEUE,
            },
            "quakestrike.infrastructure.queues.tasks.publish_prediction": {
                "queue": PREDICTION_QUEUE,
            },
        },
        "quakestrike_poll_interval_seconds": settings.poll_interval_seconds,
        "beat_scheduler": "quakestrike.scheduler.beat:DurableBeatScheduler",
        "beat_schedule": {
            "durable-ingestion-tick": {
                "task": DURABLE_INGESTION_TICK,
                "schedule": UtcBoundarySchedule(settings.poll_interval_seconds),
                "args": (),
            }
        },
    }
    if ingestion_tick is not None:
        configuration["quakestrike_scheduled_ingestion_tick"] = ingestion_tick
    app.conf.update(configuration)
    return app
