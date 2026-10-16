import pytest
from pydantic import SecretStr
from test_settings import valid_settings

from quakestrike.alert_worker.worker import configured_alert_providers, run_alert
from quakestrike.infrastructure.email.brevo import BrevoEmailProvider
from quakestrike.infrastructure.sms.iprog import IprogAlertProvider


def test_resolution_only_enablement_does_not_start_a_submission_consumer():
    settings = valid_settings().model_copy(update={"alert_resolution_enabled": True})
    with pytest.raises(ValueError, match="disabled"):
        run_alert(settings)


def test_enabled_provider_construction_requires_each_selected_channel_only():
    settings = valid_settings()
    with pytest.raises(ValueError, match="SMS"):
        configured_alert_providers(settings, channels=("sms",))
    settings.iprog_api_token = SecretStr("test-token")
    sms = configured_alert_providers(settings, channels=("sms",))
    assert isinstance(sms["sms"], IprogAlertProvider)
    with pytest.raises(ValueError, match="email"):
        configured_alert_providers(settings)
    settings.brevo_api_key = SecretStr("test-key")
    settings.brevo_sender_email = "forecast@quakestrikeph.com"
    settings.brevo_sender_name = "QuakeStrike PH - Alert System"
    providers = configured_alert_providers(settings)
    assert isinstance(providers["sms"], IprogAlertProvider)
    assert isinstance(providers["email"], BrevoEmailProvider)


def test_runtime_handler_suppresses_private_database_exception_details():
    import traceback
    from types import SimpleNamespace
    from uuid import uuid4

    from quakestrike.alert_worker.worker import create_alert_handler

    class FailedStore:
        def maintain(self, *args):
            raise RuntimeError("DETAIL destination=private@example.invalid token=private-token")

    handler = create_alert_handler(
        SimpleNamespace(alert_resolution_enabled=True, alert_delivery_enabled=True),
        store=FailedStore(),
        support=object(),
        providers={"sms": object(), "email": object()},
    )
    with pytest.raises(RuntimeError) as failure:
        handler(
            {
                "message_version": 1,
                "dispatch_id": str(uuid4()),
                "alert_job_id": str(uuid4()),
                "correlation_id": str(uuid4()),
            }
        )
    rendered = "".join(traceback.format_exception(failure.value))
    assert "private@example.invalid" not in rendered
    assert "private-token" not in rendered


def test_reconciliation_cursors_visit_later_pending_rows_and_maintenance_survives_poll_failure():
    from types import SimpleNamespace
    from uuid import UUID

    from quakestrike.alert_worker.reconciliation import AlertReconciliation

    ids = [UUID(int=value) for value in (1, 2, 3)]
    polled, maintained = [], []

    class Store:
        def iprog_poll_candidates(self, *, after, limit):
            return [
                SimpleNamespace(delivery_attempt_id=value, provider_message_id=str(value))
                for value in ids
                if after is None or value > after
            ][:limit]

        def maintenance_candidates(self, *, after, limit):
            return [
                SimpleNamespace(alert_job_id=value, dispatch_id=value, correlation_id=value)
                for value in ids
                if after is None or value > after
            ][:limit]

        def maintain(self, dispatch, job, correlation):
            maintained.append(job)
            return "delivering"

    class Provider:
        def poll(self, reference):
            polled.append(reference)
            raise RuntimeError("private destination in provider prose")

    runtime = AlertReconciliation(Store(), Provider())
    for _ in range(4):
        result = runtime.execute(limit=1)
        assert result["healthy"] is True
    assert polled == [str(value) for value in ids]
    assert maintained == ids
    assert runtime.poll_after is None and runtime.maintenance_after is None


@pytest.mark.parametrize("action", ["health-alert", "health-alert-reconciliation"])
def test_cli_exposes_read_only_alert_health_actions(monkeypatch, action):
    import sys

    from quakestrike import cli

    called = []
    monkeypatch.setattr(
        cli.operator_runtime, "worker_health", lambda name: called.append(name) or 0
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", action])
    assert cli.main() == 0
    assert called == [action]


def test_alert_health_requires_local_queue_consumption_and_fresh_reconciliation_marker(
    monkeypatch, tmp_path
):
    import os
    import socket
    import time
    from types import SimpleNamespace

    from quakestrike import operator_runtime
    from quakestrike.alert_worker import reconciliation

    live_probes = []
    # Windows signal 0 sends CTRL_C_EVENT; isolate the Linux container liveness probe.
    monkeypatch.setattr(operator_runtime.os, "kill", lambda pid, signal: live_probes.append(pid))
    worker = f"alert-worker@{socket.gethostname()}"
    queues = {"alert-worker@some-other-container": [{"name": "alert"}]}
    monkeypatch.setattr(
        operator_runtime,
        "create_celery_app",
        lambda _: SimpleNamespace(
            control=SimpleNamespace(
                inspect=lambda **kwargs: SimpleNamespace(active_queues=lambda: queues)
            )
        ),
    )
    assert operator_runtime.alert_consuming(valid_settings(), local_only=True) is False
    queues[worker] = [{"name": "alert"}]
    assert operator_runtime.alert_consuming(valid_settings(), local_only=True) is True
    marker = tmp_path / "scan"
    monkeypatch.setattr(reconciliation, "SCAN_HEALTH_MARKER", marker)
    assert operator_runtime.reconciliation_running(valid_settings()) is False
    marker.write_text(str(os.getpid()), encoding="ascii")
    assert operator_runtime.reconciliation_running(valid_settings()) is True
    assert live_probes == [os.getpid()]
    old = time.time() - 121
    os.utime(marker, (old, old))
    assert operator_runtime.reconciliation_running(valid_settings()) is False


def test_operator_retirement_masks_private_store_errors(monkeypatch, capsys):
    from contextlib import contextmanager

    from quakestrike.alert_worker import operations

    class Store:
        def preview_legacy_alerts(self):
            raise RuntimeError("DETAIL private@example.invalid private-password")

    @contextmanager
    def configured(settings):
        yield Store()

    monkeypatch.setattr(operations, "Settings", valid_settings)
    monkeypatch.setattr(operations, "alert_store", configured)
    from types import SimpleNamespace

    monkeypatch.setattr(
        operations,
        "AlembicMigrationStateGate",
        lambda _: SimpleNamespace(check=lambda: SimpleNamespace(ready=True)),
    )
    assert operations.retire_legacy_alerts() == 2
    output = capsys.readouterr().out
    assert "private@example.invalid" not in output
    assert "private-password" not in output
    assert "unavailable" in output


def test_alert_health_recovers_after_bounded_database_and_broker_failures(monkeypatch, capsys):
    from types import SimpleNamespace

    from quakestrike import operator_runtime
    from quakestrike.infrastructure import alert_readiness

    available = {"database": True, "broker": True}
    monkeypatch.setattr(operator_runtime, "Settings", valid_settings)

    def gate(name):
        return lambda _: SimpleNamespace(check=lambda: SimpleNamespace(ready=available[name]))

    monkeypatch.setattr(operator_runtime, "PostgresConnectivityHealthCheck", gate("database"))
    monkeypatch.setattr(operator_runtime, "RedisConnectivityHealthCheck", gate("broker"))

    def ready(_, **kwargs):
        return SimpleNamespace(check=lambda: SimpleNamespace(ready=True))

    monkeypatch.setattr(operator_runtime, "AlembicMigrationStateGate", ready)
    monkeypatch.setattr(alert_readiness, "AlertReadinessGate", ready)
    monkeypatch.setattr(operator_runtime, "alert_consuming", lambda *args, **kwargs: True)
    for dependency in available:
        available[dependency] = False
        assert operator_runtime.worker_health("health-alert") == 2
        available[dependency] = True
        assert operator_runtime.worker_health("health-alert") == 0
    output = capsys.readouterr().out
    assert "unhealthy" in output and "healthy" in output
    import json

    assert all(
        json.loads(line)["provider_authentication"] == "unverified" for line in output.splitlines()
    )


@pytest.mark.parametrize("failure_phase", ["persistence", "maintenance"])
def test_reconciliation_advances_after_one_record_database_failure(failure_phase):
    from types import SimpleNamespace
    from uuid import UUID

    from quakestrike.application.alert_reconciliation import AlertReconciliation
    from quakestrike.application.sms_polling import SmsOutcome

    ids = [UUID(int=value) for value in (1, 2, 3)]
    polled, persisted, reports = [], [], []

    class Store:
        def iprog_poll_candidates(self, *, after, limit):
            return [
                SimpleNamespace(
                    delivery_attempt_id=value,
                    provider_message_id=str(value),
                    alert_job_id=value,
                    dispatch_id=value,
                    correlation_id=value,
                )
                for value in ids
                if after is None or value > after
            ][:limit]

        def reconcile_delivery(self, attempt_id, *args, **kwargs):
            if attempt_id == ids[0] and failure_phase == "persistence":
                raise RuntimeError("DETAIL private@example.invalid private-password")
            persisted.append(attempt_id)
            return "applied"

        def maintain(self, dispatch_id, *args):
            if dispatch_id == ids[0] and failure_phase == "maintenance":
                raise RuntimeError("DETAIL private@example.invalid private-password")

        def maintenance_candidates(self, **kwargs):
            return []

    class Provider:
        def poll(self, reference):
            polled.append(reference)
            return SmsOutcome("accepted")

    runtime = AlertReconciliation(
        Store(), Provider(), report=lambda *args: reports.append(args[-1])
    )
    results = [runtime.execute(limit=1) for _ in ids]
    assert polled == [str(value) for value in ids]
    assert ids[1:] == [value for value in persisted if value != ids[0]]
    assert results[0]["healthy"] is False
    assert results[1]["healthy"] is True
    assert reports[0] == "poll_reconciliation_unavailable"


def test_finite_reconciliation_reports_database_failure_without_claiming_success():
    from types import SimpleNamespace
    from uuid import UUID

    from quakestrike.alert_worker.controlled import run_controlled_alert
    from quakestrike.application.sms_polling import SmsOutcome

    settings = valid_settings().model_copy(
        update={
            "database_url": "postgresql+psycopg://quakestrike_worker:fixture@postgres-test:5432/quakestrike_test",
            "redis_url": "redis://redis-test:6379/0",
            "iprog_api_token": SecretStr("simulated-token"),
            "alert_test_sms_destination": SecretStr("+639171234567"),
        }
    )
    selected = UUID(int=1)

    class Store:
        def controlled_fixture_is_valid(self, *args, **kwargs):
            return True

        def iprog_poll_candidates(self, **kwargs):
            assert kwargs["alert_job_id"] == selected
            return [
                SimpleNamespace(
                    delivery_attempt_id=selected,
                    alert_job_id=selected,
                    dispatch_id=selected,
                    correlation_id=selected,
                    provider_message_id="selected-reference",
                )
            ]

        def reconcile_delivery(self, *args, **kwargs):
            raise RuntimeError("DETAIL private@example.invalid private-password")

        def maintain(self, *args):
            return None

    class Provider:
        def poll(self, reference):
            return SmsOutcome("delivered")

    payload = {
        "message_version": 1,
        "alert_job_id": str(selected),
        "dispatch_id": str(selected),
        "correlation_id": str(selected),
    }
    with pytest.raises(RuntimeError, match="unavailable"):
        run_controlled_alert(
            settings,
            payload,
            selected,
            channels=("sms",),
            store=Store(),
            support=object(),
            providers={"sms": Provider()},
            reconcile=True,
        )
