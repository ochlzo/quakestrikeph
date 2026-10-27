from __future__ import annotations

import logging

import pytest
from celery.exceptions import Reject

from quakestrike.infrastructure.settings import Settings
from quakestrike.prediction_worker import worker


def settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/catalog",
        model_release_id="00000000-0000-0000-0000-000000000001",
    )


def test_failed_prediction_task_logs_safe_command_identifiers(caplog, monkeypatch) -> None:
    payload = {
        "message_version": 1,
        "dispatch_id": "00000000-0000-0000-0000-000000000001",
        "job_id": "00000000-0000-0000-0000-000000000002",
        "correlation_id": "00000000-0000-0000-0000-000000000003",
    }

    def fail(_payload):
        raise RuntimeError("sensitive detail")

    task_name = "quakestrike.prediction_worker.test_failed_command"
    monkeypatch.setattr(worker, "PREDICTION_TASK_NAME", task_name)
    app = worker.create_prediction_app(settings(), command_handler=fail)
    task = app.tasks[task_name]
    assert task.soft_time_limit == 300
    assert task.time_limit == 360
    assert task.acks_late is True
    assert task.reject_on_worker_lost is True
    with caplog.at_level(logging.ERROR, logger="prediction-worker"):
        with pytest.raises(Reject):
            task.run(payload)
    record = next(
        record
        for record in caplog.records
        if record.event_code == "prediction_command_processing_failed"
    )
    assert record.context["dispatch_id"] == payload["dispatch_id"]
    assert record.context["job_id"] == payload["job_id"]
    assert record.context["correlation_id"] == payload["correlation_id"]
    assert "sensitive detail" not in str(record.context)
