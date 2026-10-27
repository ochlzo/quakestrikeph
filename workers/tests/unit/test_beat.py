from __future__ import annotations

import io
import json
from datetime import UTC, datetime

from quakestrike.infrastructure.logging.json_logging import configure_logging
from quakestrike.infrastructure.queues.celery_app import (
    DURABLE_INGESTION_TICK,
    UtcBoundarySchedule,
    create_celery_app,
)
from quakestrike.infrastructure.settings import Settings
from quakestrike.scheduler.beat import DurableBeatScheduler


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id="00000000-0000-0000-0000-000000000001",
    )


def test_due_beat_entry_runs_local_tick_without_publishing_a_task() -> None:
    ticks: list[str] = []
    app = create_celery_app(_settings(), ingestion_tick=lambda: ticks.append("created"))
    assert set(app.conf.beat_schedule) == {"durable-ingestion-tick"}
    schedule = app.conf.beat_schedule["durable-ingestion-tick"]
    assert schedule["task"] == DURABLE_INGESTION_TICK
    assert isinstance(schedule["schedule"], UtcBoundarySchedule)
    assert schedule["schedule"].interval_seconds == 300
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
    app.connection_for_write = lambda *args, **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("Beat must not connect to the broker")
    )
    scheduler = DurableBeatScheduler(app)
    assert scheduler.producer is None
    app.send_task = lambda *args, **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("Beat must not publish a queue task")
    )

    entry = scheduler.schedule["durable-ingestion-tick"]
    assert entry.task == DURABLE_INGESTION_TICK
    scheduler.apply_entry(entry)

    assert ticks == ["created"]


def test_new_beat_scheduler_waits_for_the_next_boundary_before_writing() -> None:
    now = [datetime(2026, 9, 18, 12, 2, tzinfo=UTC)]
    writes: list[str] = []
    app = create_celery_app(_settings(), ingestion_tick=lambda: writes.append("run"))
    app.now = lambda: now[0]  # type: ignore[method-assign]
    app.conf.beat_schedule["durable-ingestion-tick"]["schedule"] = UtcBoundarySchedule(
        300, nowfun=lambda: now[0]
    )
    schedule = app.conf.beat_schedule["durable-ingestion-tick"]["schedule"]
    started_at = now[0]
    due, remaining = schedule.is_due(started_at)
    assert due is False
    assert remaining == 180
    scheduler = DurableBeatScheduler(app)

    assert scheduler.tick() > 0
    assert writes == []

    now[0] = datetime(2026, 9, 18, 12, 5, tzinfo=UTC)
    assert schedule.is_due(started_at).is_due is True
    assert schedule.is_due(now[0]).is_due is False
    scheduler.tick()
    assert writes == ["run"]
    scheduler.tick()
    assert writes == ["run"]


def test_beat_tick_failure_uses_structured_redacted_logging() -> None:
    output = io.StringIO()
    configure_logging("scheduler-beat", level="INFO", stream=output)
    app = create_celery_app(
        _settings(),
        ingestion_tick=lambda: (_ for _ in ()).throw(
            RuntimeError("redis://worker:secret@example.invalid/0?password=must-not-log")
        ),
    )
    scheduler = DurableBeatScheduler(app)

    scheduler.apply_entry(scheduler.schedule["durable-ingestion-tick"])

    record = json.loads(output.getvalue())
    assert record["event_code"] == "scheduled_ingestion_tick_failed"
    assert record["context"]["exception_type"] == "RuntimeError"
    assert "secret" not in output.getvalue()
    assert "password" not in output.getvalue()
