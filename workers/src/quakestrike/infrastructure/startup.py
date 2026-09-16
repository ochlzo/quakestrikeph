"""Phase 1 startup adapters that deliberately report unavailable gates."""

from __future__ import annotations

from dataclasses import dataclass

from quakestrike.application.startup import GateResult, StartupGate
from quakestrike.infrastructure.database.migration_state import AlembicMigrationStateGate
from quakestrike.infrastructure.health import (
    PostgresConnectivityHealthCheck,
    RedisConnectivityHealthCheck,
)
from quakestrike.infrastructure.settings import Settings


@dataclass(frozen=True, slots=True)
class UnavailableStartupGate:
    """A read-only placeholder until a later phase supplies its adapter."""

    name: str
    reason: str

    def check(self) -> GateResult:
        return GateResult(name=self.name, ready=False, reason=self.reason)


def phase_one_startup_gates(
    settings: Settings,
    *,
    database_gate: StartupGate | None = None,
    redis_gate: StartupGate | None = None,
    migration_gate: StartupGate | None = None,
) -> tuple[StartupGate, ...]:
    """Return the fail-closed gates required by the Phase 1 contract."""

    return (
        migration_gate or AlembicMigrationStateGate(settings),
        UnavailableStartupGate(
            name="model-release",
            reason="Model-release verification is deferred to Phase 3.",
        ),
        UnavailableStartupGate(
            name="bootstrap-readiness",
            reason="Bootstrap readiness is deferred to Phase 8.",
        ),
        database_gate or PostgresConnectivityHealthCheck(settings),
        redis_gate or RedisConnectivityHealthCheck(settings),
    )
