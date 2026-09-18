from __future__ import annotations

import io
import json
from datetime import UTC, datetime

from celery import Celery

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
    scheduler = DurableBeatScheduler(app)
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
    scheduler = DurableBeatScheduler(app)

    assert scheduler.tick() > 0
    assert writes == []

    now[0] = datetime(2026, 9, 18, 12, 5, tzinfo=UTC)
    scheduler.tick()
    assert writes == ["run"]


def test_scheduler_can_be_constructed_by_celery_with_the_configured_class() -> None:
    app = Celery("test", broker="memory://")
    app.conf.update(
        beat_schedule={
            "durable-ingestion-tick": {
                "task": DURABLE_INGESTION_TICK,
                "schedule": 300,
            }
        },
        quakestrike_scheduled_ingestion_tick=lambda: None,
    )

    scheduler = DurableBeatScheduler(app)

    assert scheduler.schedule["durable-ingestion-tick"].task == DURABLE_INGESTION_TICK
    assert set(scheduler.schedule) == {"durable-ingestion-tick"}


def test_scheduler_does_not_construct_a_broker_producer() -> None:
    app = Celery("test", broker="redis://invalid.example:6379/0")
    app.conf.update(
        beat_schedule={
            "durable-ingestion-tick": {
                "task": DURABLE_INGESTION_TICK,
                "schedule": 300,
            }
        },
        quakestrike_scheduled_ingestion_tick=lambda: None,
    )
    app.connection_for_write = lambda *args, **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("Beat must not connect to the broker")
    )
    scheduler = DurableBeatScheduler(app)

    assert scheduler.producer is None


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
