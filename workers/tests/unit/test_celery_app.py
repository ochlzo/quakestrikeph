from __future__ import annotations

from datetime import timedelta

from quakestrike.infrastructure.queues.celery_app import (
    DURABLE_INGESTION_TICK,
    create_celery_app,
)
from quakestrike.infrastructure.settings import Settings


def test_celery_configuration_declares_one_durable_five_minute_poll() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id="00000000-0000-0000-0000-000000000001",
    )

    app = create_celery_app(settings)

    assert set(app.conf.beat_schedule) == {"durable-ingestion-tick"}
    schedule = app.conf.beat_schedule["durable-ingestion-tick"]
    assert schedule["task"] == DURABLE_INGESTION_TICK
    assert schedule["schedule"] == timedelta(seconds=300)
    assert schedule["args"] == ()
    assert app.conf.beat_scheduler == "quakestrike.scheduler.beat:DurableBeatScheduler"
    assert app.conf.quakestrike_poll_interval_seconds == 300
    assert DURABLE_INGESTION_TICK not in app.conf.task_routes
    assert (
        app.conf.task_routes["quakestrike.data_ingestor.worker.process_ingestion"]["queue"]
        == "ingestion"
    )
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_concurrency == 1
    assert app.conf.task_ignore_result is True
    assert (
        app.conf.task_routes["quakestrike.infrastructure.queues.tasks.publish_prediction"]["queue"]
        == "prediction"
    )
