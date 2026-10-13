import json
from types import SimpleNamespace
from unittest.mock import Mock

from redis.exceptions import RedisError

from quakestrike.alert_testing import runtime


def test_runtime_startup_and_maintenance_emit_sanitized_json(monkeypatch, tmp_path, capsys):
    (tmp_path / "index.html").write_text("private app")
    secret_url = "redis://operator:private-password@private-host/0"
    monkeypatch.setenv("ALERT_TEST_REDIS_URL", secret_url)
    monkeypatch.setenv("ALERT_TEST_PREPARATION_KEY", "test-only-preparation-key-32-bytes")
    monkeypatch.setattr("sys.argv", ["alert-testing", "--static-directory", str(tmp_path)])
    client = Mock()
    monkeypatch.setattr(runtime.Redis, "from_url", Mock(return_value=client))
    monkeypatch.setattr(runtime, "RedisSessionStore", Mock(return_value=object()))
    sessions = Mock()
    sessions.maintain.side_effect = RedisError(secret_url + " operator@example.invalid")
    monkeypatch.setattr(runtime, "Sessions", Mock(return_value=sessions))
    server = SimpleNamespace(
        origin="https://private-operator.private-tailnet.ts.net",
        server_port=4341,
        serve_forever=Mock(side_effect=KeyboardInterrupt),
        server_close=Mock(),
    )
    monkeypatch.setattr(runtime, "PrivateServer", Mock(return_value=server))
    stopped = Mock()
    stopped.wait.side_effect = [False, True]
    monkeypatch.setattr(runtime, "Event", Mock(return_value=stopped))

    def thread(*, target, daemon):
        return SimpleNamespace(start=target, join=Mock())

    monkeypatch.setattr(runtime, "Thread", thread)
    runtime.main()
    captured = capsys.readouterr()
    records = [json.loads(line) for line in captured.out.splitlines()]
    by_event = {record["event_code"]: record for record in records}
    assert len(records) == 2
    assert all(record["service"] == "alert-testing" for record in records)
    startup = by_event["alert_testing_started"]
    assert startup["level"] == "info"
    assert "127.0.0.1:4341" in startup["message"]
    assert startup["context"] == {"operation": "private_http", "status": "listening"}
    outage = by_event["alert_testing_dependency_unavailable"]
    assert outage["level"] == "warning"
    assert outage["context"] == {
        "operation": "session_maintenance",
        "reason": "redis_unavailable",
    }
    assert not captured.err
    for private_value in (
        secret_url,
        "private-password",
        "operator@example.invalid",
        server.origin,
    ):
        assert private_value not in captured.out
    sessions.maintain.assert_called_once()
    stopped.set.assert_called_once()
    client.close.assert_called_once()
