from __future__ import annotations

from quakestrike.infrastructure import startup
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import (
    UnavailableStartupGate,
)
from quakestrike.runtime import run_service


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
