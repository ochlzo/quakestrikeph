from __future__ import annotations

from quakestrike.application.startup import evaluate_startup_gates
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import UnavailableStartupGate, phase_one_startup_gates


def valid_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id="00000000-0000-0000-0000-000000000001",
    )


def phase_one_test_gates() -> tuple:
    return phase_one_startup_gates(
        valid_settings(),
        migration_gate=UnavailableStartupGate(
            name="migration-state",
            reason="Test migration database is unavailable.",
        ),
        database_gate=UnavailableStartupGate(
            name="postgres-connectivity",
            reason="Test database is unavailable.",
        ),
        redis_gate=UnavailableStartupGate(
            name="redis-connectivity",
            reason="Test Redis is unavailable.",
        ),
    )


def test_phase_one_gates_are_read_only_and_fail_closed() -> None:
    report = evaluate_startup_gates(phase_one_test_gates())

    assert report.ready is False
    assert report.failed_gate_names == (
        "migration-state",
        "model-release",
        "bootstrap-readiness",
        "postgres-connectivity",
        "redis-connectivity",
    )
    assert all(result.ready is False for result in report.results)
    assert all(result.reason for result in report.results)


def test_startup_report_exposes_sanitized_gate_details() -> None:
    report = evaluate_startup_gates(phase_one_test_gates())

    serialized = report.as_dict()

    assert serialized["ready"] is False
    assert serialized["failed_gate_names"] == [
        "migration-state",
        "model-release",
        "bootstrap-readiness",
        "postgres-connectivity",
        "redis-connectivity",
    ]
    assert "DATABASE_URL" not in str(serialized)
