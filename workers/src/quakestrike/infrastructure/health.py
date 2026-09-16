"""Read-only PostgreSQL and Redis connectivity health adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import redis
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from quakestrike.application.startup import GateResult
from quakestrike.infrastructure.settings import Settings

EngineFactory = Callable[[str], Engine]
RedisClientFactory = Callable[[str], Redis]


def _create_postgres_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        connect_args={"connect_timeout": 5},
        pool_pre_ping=True,
    )


def _create_redis_client(redis_url: str) -> Redis:
    return redis.Redis.from_url(
        redis_url,
        socket_connect_timeout=5,
        socket_timeout=5,
    )


@dataclass(frozen=True, slots=True)
class PostgresConnectivityHealthCheck:
    """Check PostgreSQL with one read-only statement and no schema changes."""

    settings: Settings
    engine_factory: EngineFactory = _create_postgres_engine

    name: str = "postgres-connectivity"

    def check(self) -> GateResult:
        try:
            engine = self.engine_factory(self.settings.database_url)
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
            finally:
                engine.dispose()
        except Exception as error:
            return GateResult(
                name=self.name,
                ready=False,
                reason="PostgreSQL connectivity is unavailable.",
                details={"error_type": type(error).__name__},
            )

        return GateResult(
            name=self.name,
            ready=True,
            reason="PostgreSQL accepted a read-only connectivity probe.",
            details={"probe": "SELECT 1"},
        )


@dataclass(frozen=True, slots=True)
class RedisConnectivityHealthCheck:
    """Check Redis with PING and no key or configuration mutations."""

    settings: Settings
    client_factory: RedisClientFactory = _create_redis_client

    name: str = "redis-connectivity"

    def check(self) -> GateResult:
        client: Redis | None = None
        try:
            client = self.client_factory(self.settings.redis_url)
            client.ping()
        except Exception as error:
            return GateResult(
                name=self.name,
                ready=False,
                reason="Redis connectivity is unavailable.",
                details={"error_type": type(error).__name__},
            )
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

        return GateResult(
            name=self.name,
            ready=True,
            reason="Redis accepted a read-only PING probe.",
            details={"probe": "PING"},
        )
