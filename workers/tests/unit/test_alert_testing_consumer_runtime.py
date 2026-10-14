import json
from unittest.mock import Mock

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from quakestrike.alert_testing import consumer_runtime as runtime
from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.infrastructure.accounts import AccountAccessUnavailable


def test_consumer_logs_bounded_sanitized_failure_and_recovery(monkeypatch, capsys):
    private = "secret destination@example.invalid message body redis://secret"
    monkeypatch.setenv("ALERT_TEST_CONSUMER_ENABLED", "true")
    monkeypatch.setenv("ALERT_TEST_REDIS_URL", "redis://fixture")
    monkeypatch.setenv("ALERT_TEST_DATABASE_URL", "postgresql://fixture")
    client, engine = Mock(), Mock()
    monkeypatch.setattr(runtime.Redis, "from_url", Mock(return_value=client))
    monkeypatch.setattr(runtime, "create_engine", Mock(return_value=engine))
    sessions = Mock()
    sessions.read.side_effect = [
        RedisError(private),
        RedisError(private),
        SessionConflict(),
        {"status": "inactive"},
        SQLAlchemyError(private),
        AccountAccessUnavailable(private),
        {"status": "inactive"},
        {"status": "active", "session_id": "fixture-owner"},
        KeyboardInterrupt(),
    ]
    monkeypatch.setattr(runtime, "Sessions", Mock(return_value=sessions))
    monkeypatch.setattr(runtime, "RedisDeliveryStore", Mock(return_value=Mock()))
    consumer = Mock()
    consumer.once.return_value = True
    monkeypatch.setattr(runtime, "Consumer", Mock(return_value=consumer))
    reconciliation_factory = Mock(return_value=Mock())
    monkeypatch.setattr(runtime, "Reconciliation", reconciliation_factory)
    monkeypatch.setattr(runtime.time, "sleep", Mock())
    heartbeat = Mock()
    monkeypatch.setattr(runtime, "mark_consumer", heartbeat)
    runtime.main()
    output = capsys.readouterr()
    records = [json.loads(line) for line in output.out.splitlines()]
    assert [row["event_code"] for row in records] == [
        "alert_testing_consumer_dependency_unavailable",
        "alert_testing_consumer_dependency_recovered",
        "alert_testing_consumer_dependency_unavailable",
        "alert_testing_consumer_dependency_recovered",
    ]
    assert [row["context"]["reason"] for row in records] == [
        "redis_unavailable",
        "redis_unavailable",
        "accounts_unavailable",
        "accounts_unavailable",
    ]
    assert all(row["service"] == "alert-testing-consumer" for row in records)
    assert private not in output.out and not output.err
    client.close.assert_called_once()
    engine.dispose.assert_called_once()
    consumer.once.assert_called_once_with("fixture-owner")
    heartbeat.assert_called_once()
    assert isinstance(reconciliation_factory.call_args.kwargs["report"], runtime.PollingDiagnostics)
