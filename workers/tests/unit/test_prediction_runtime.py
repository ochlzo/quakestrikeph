from __future__ import annotations

from types import SimpleNamespace

from quakestrike.infrastructure.models.deterministic_test import DeterministicTestModel
from quakestrike.infrastructure.queues.prediction_publisher import PREDICTION_TASK_NAME
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


def test_prediction_task_limits_fit_the_lease() -> None:
    app = worker.create_prediction_app(settings(), command_handler=lambda _: "unclaimed")
    task = app.tasks[PREDICTION_TASK_NAME]

    assert task.soft_time_limit == 300
    assert task.time_limit == 360
    assert task.acks_late is True
    assert task.reject_on_worker_lost is True


def test_prediction_worker_runs_one_prefork_child(monkeypatch) -> None:
    arguments = []
    monkeypatch.setattr(
        worker,
        "create_prediction_app",
        lambda *_, **__: SimpleNamespace(worker_main=lambda args: arguments.extend(args)),
    )

    assert worker.run_prediction(settings(), model=DeterministicTestModel()) == 0
    assert arguments[arguments.index("--pool") + 1] == "prefork"
    assert arguments[arguments.index("--concurrency") + 1] == "1"
