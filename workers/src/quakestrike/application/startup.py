"""Read-only startup gate interfaces shared by worker entry points."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GateResult:
    """The result of one startup prerequisite check."""

    name: str
    ready: bool
    reason: str
    details: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ready": self.ready,
            "reason": self.reason,
            "details": dict(self.details),
        }


class StartupGate(Protocol):
    """The small interface every read-only startup gate must provide."""

    name: str

    def check(self) -> GateResult:
        """Return a result without mutating application state."""


class MigrationStateGate(StartupGate, Protocol):
    """Reports whether the database migration state is usable."""


class ModelReleaseVerificationGate(StartupGate, Protocol):
    """Reports whether the configured immutable model release is verified."""


class BootstrapReadinessGate(StartupGate, Protocol):
    """Reports whether the finite history bootstrap has passed its gates."""


class DatabaseConnectivityHealth(StartupGate, Protocol):
    """Reports whether PostgreSQL accepts a read-only connectivity probe."""


class RedisConnectivityHealth(StartupGate, Protocol):
    """Reports whether Redis accepts a read-only ping probe."""


@dataclass(frozen=True, slots=True)
class StartupReport:
    """Aggregate result used by service entry points and health output."""

    results: tuple[GateResult, ...]

    @property
    def ready(self) -> bool:
        return bool(self.results) and all(result.ready for result in self.results)

    @property
    def failed_gate_names(self) -> tuple[str, ...]:
        return tuple(result.name for result in self.results if not result.ready)

    def as_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "failed_gate_names": list(self.failed_gate_names),
            "results": [result.as_dict() for result in self.results],
        }


def evaluate_startup_gates(gates: Iterable[StartupGate]) -> StartupReport:
    """Evaluate all gates and fail closed when none are configured."""

    results: list[GateResult] = []
    for gate in gates:
        try:
            results.append(gate.check())
        except Exception as error:
            results.append(
                GateResult(
                    name=getattr(gate, "name", "startup-gate"),
                    ready=False,
                    reason="Startup gate failed safely.",
                    details={"error_type": _safe_error_type(error)},
                )
            )
    if results:
        return StartupReport(tuple(results))

    return StartupReport(
        (
            GateResult(
                name="startup-gates",
                ready=False,
                reason="No startup gates were configured.",
            ),
        )
    )


def _safe_error_type(error: BaseException) -> str:
    name = type(error).__name__
    return name if name and len(name) <= 100 and name.isidentifier() else "UnknownError"
