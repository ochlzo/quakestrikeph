from __future__ import annotations

from quakestrike.infrastructure.health import (
    PostgresConnectivityHealthCheck,
    RedisConnectivityHealthCheck,
)
from quakestrike.infrastructure.settings import Settings


def valid_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id="00000000-0000-0000-0000-000000000001",
    )


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[object] = []

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: object) -> None:
        self.statements.append(statement)


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()
        self.disposed = False

    def connect(self) -> FakeConnection:
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


class FakeRedis:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.ping_count = 0
        self.closed = False

    def ping(self) -> bool:
        self.ping_count += 1
        if self.should_fail:
            raise ConnectionError("redis is offline")
        return True

    def close(self) -> None:
        self.closed = True


def test_postgres_health_uses_a_read_only_probe_and_closes_engine() -> None:
    engine = FakeEngine()

    result = PostgresConnectivityHealthCheck(
        valid_settings(),
        engine_factory=lambda _url: engine,
    ).check()

    assert result.name == "postgres-connectivity"
    assert result.ready is True
    assert len(engine.connection.statements) == 1
    assert str(engine.connection.statements[0]) == "SELECT 1"
    assert engine.disposed is True


def test_postgres_health_reports_unavailable_without_exposing_connection_details() -> None:
    def failing_engine(_url: str) -> FakeEngine:
        raise ConnectionError("postgres password=secret is offline")

    result = PostgresConnectivityHealthCheck(
        valid_settings(),
        engine_factory=failing_engine,
    ).check()

    assert result.name == "postgres-connectivity"
    assert result.ready is False
    assert result.reason == "PostgreSQL connectivity is unavailable."
    assert result.details == {"error_type": "ConnectionError"}
    assert "secret" not in str(result.as_dict())


def test_redis_health_pings_and_closes_client() -> None:
    client = FakeRedis()

    result = RedisConnectivityHealthCheck(
        valid_settings(),
        client_factory=lambda _url: client,
    ).check()

    assert result.name == "redis-connectivity"
    assert result.ready is True
    assert client.ping_count == 1
    assert client.closed is True


def test_redis_health_reports_unavailable_and_closes_client() -> None:
    client = FakeRedis(should_fail=True)

    result = RedisConnectivityHealthCheck(
        valid_settings(),
        client_factory=lambda _url: client,
    ).check()

    assert result.name == "redis-connectivity"
    assert result.ready is False
    assert result.reason == "Redis connectivity is unavailable."
    assert result.details == {"error_type": "ConnectionError"}
    assert client.closed is True
