from unittest.mock import MagicMock

import pytest
from redis.exceptions import ConnectionError

from quakestrike.alert_testing import health


def test_consumer_health_requires_a_live_process_and_usable_redis(tmp_path, monkeypatch):
    marker = tmp_path / "health"
    monkeypatch.setattr(health, "CONSUMER_MARKER", marker)
    # Production probes run on Linux; Windows does not implement POSIX signal zero.
    monkeypatch.setattr(health.os, "kill", lambda *_: None)
    monkeypatch.setenv("ALERT_TEST_REDIS_URL", "redis://disposable")
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr(health.Redis, "from_url", lambda *_, **__: client)
    with pytest.raises(FileNotFoundError):
        health.check_consumer()
    health.mark_consumer()
    health.check_consumer()
    client.ping.side_effect = ConnectionError("unavailable")
    with pytest.raises(ConnectionError):
        health.check_consumer()
    client.ping.side_effect = None
    monkeypatch.setattr(health.os, "kill", lambda *_: (_ for _ in ()).throw(ProcessLookupError()))
    health.mark_consumer()
    with pytest.raises(ProcessLookupError):
        health.check_consumer()
