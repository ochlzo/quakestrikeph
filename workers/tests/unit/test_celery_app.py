from __future__ import annotations

from quakestrike.infrastructure.queues.celery_app import create_celery_app
from quakestrike.infrastructure.settings import Settings


def test_celery_configuration_preserves_poll_interval_without_scheduling_work() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id="00000000-0000-0000-0000-000000000001",
    )

    app = create_celery_app(settings)

    assert app.conf.beat_schedule == {}
    assert app.conf.quakestrike_poll_interval_seconds == 300
    assert "quakestrike.scheduler.beat.create_ingestion_run" not in app.conf.task_routes
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
