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


def test_ready_service_invokes_the_injected_runtime_runner() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id="00000000-0000-0000-0000-000000000001",
    )
    received = []

    class ReadyGate:
        name = "ready"

        def check(self):  # type: ignore[no-untyped-def]
            return startup.GateResult(name=self.name, ready=True, reason="ready")

    exit_code = run_service(
        "scheduler-dispatcher",
        settings_factory=lambda: settings,
        gate_factory=lambda current: (ReadyGate(),),
        runtime=lambda current: received.append(current) or 0,
    )

    assert exit_code == 0
    assert received == [settings]


def test_runtime_failure_logs_only_a_sanitized_exception_type(capsys) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id="00000000-0000-0000-0000-000000000001",
    )

    class ReadyGate:
        name = "ready"

        def check(self):  # type: ignore[no-untyped-def]
            return startup.GateResult(name=self.name, ready=True, reason="ready")

    def fail(_settings: Settings) -> int:
        raise RuntimeError("redis://worker:secret@example.invalid/0?password=must-not-log")

    exit_code = run_service(
        "scheduler-dispatcher",
        settings_factory=lambda: settings,
        gate_factory=lambda current: (ReadyGate(),),
        runtime=fail,
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert '"event_code":"service_runtime_failed"' in output
    assert '"exception_type":"RuntimeError"' in output
    assert "secret" not in output
    assert "password" not in output


def test_beat_refuses_to_start_when_bootstrap_readiness_is_not_ready() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id="00000000-0000-0000-0000-000000000001",
    )
    started: list[bool] = []

    exit_code = run_service(
        "scheduler-beat",
        settings_factory=lambda: settings,
        gate_factory=lambda _settings: (
            UnavailableStartupGate(
                name="bootstrap-readiness",
                reason="Bootstrap readiness evidence is unavailable or invalid.",
            ),
        ),
        runtime=lambda _settings: started.append(True) or 0,
    )

    assert exit_code == 2
    assert started == []
