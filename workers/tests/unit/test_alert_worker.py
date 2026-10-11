import pytest
from celery.exceptions import Reject
from test_settings import valid_settings

from quakestrike.alert_worker.worker import create_alert_app, run_alert
from quakestrike.infrastructure.queues.alert_publisher import ALERT_TASK_NAME


def test_partial_runtime_is_disabled_by_default():
    settings = valid_settings()
    assert settings.alert_resolution_enabled is False
    with pytest.raises(ValueError, match="disabled"):
        run_alert(settings)


def test_alert_task_consumes_existing_route_and_requeues_infrastructure_failures():
    settings = valid_settings()

    def failed(payload):
        raise RuntimeError("secret@example.invalid")

    app = create_alert_app(settings, command_handler=failed)
    task = app.tasks[ALERT_TASK_NAME]
    assert task.acks_late is True
    assert task.reject_on_worker_lost is True
    assert task.acks_on_failure_or_timeout is False
    with pytest.raises(Reject) as failure:
        task.run({})
    assert failure.value.requeue is True
    assert "secret" not in str(failure.value)
