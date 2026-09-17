from __future__ import annotations

from quakestrike.infrastructure import startup
from quakestrike.infrastructure.models.release_manifest import ManifestValidationError
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import (
    ModelReleaseStartupGate,
    UnavailableStartupGate,
    phase_one_startup_gates,
)
from quakestrike.runtime import run_service


def test_entrypoint_refuses_work_when_phase_one_gates_are_unavailable(capsys) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id="00000000-0000-0000-0000-000000000001",
    )

    exit_code = run_service(
        "scheduler-dispatcher",
        settings_factory=lambda: settings,
        gate_factory=lambda current_settings: phase_one_startup_gates(
            current_settings,
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
        ),
    )

    assert exit_code == 2
    output = capsys.readouterr().out
    assert '"gate":"postgres-connectivity"' in output
    assert '"gate":"redis-connectivity"' in output


def test_unverified_release_stops_service_before_runtime_work(monkeypatch, capsys) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id="2f532893-7a25-4f18-814c-91d66f38dac4",
    )
    monkeypatch.setattr(
        startup,
        "load_verified_release_manifest",
        lambda *_, **__: (_ for _ in ()).throw(ManifestValidationError("changed weight")),
    )

    exit_code = run_service(
        "data-ingestor",
        settings_factory=lambda: settings,
        gate_factory=lambda current: (ModelReleaseStartupGate(current),),
    )

    output = capsys.readouterr().out
    assert exit_code == 2
    assert '"event_code":"startup_not_ready"' in output
    assert '"event_code":"phase_one_runtime_deferred"' not in output
    assert "changed weight" not in output
