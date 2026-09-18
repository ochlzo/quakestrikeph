from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from quakestrike import cli, operator_runtime, operator_setup
from quakestrike.application.persistence import RunDispatchResult
from quakestrike.application.startup import GateResult


def test_verify_release_is_a_separate_read_only_action(monkeypatch, capsys) -> None:
    monkeypatch.setattr(operator_setup, "Settings", lambda: object())
    monkeypatch.setattr(
        operator_setup,
        "ModelReleaseStartupGate",
        lambda _: SimpleNamespace(
            check=lambda: GateResult("model-release", True, "Verified.", {"release_id": "abc"})
        ),
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "verify-model-release"])

    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "verified"


def test_migration_is_an_explicit_action(monkeypatch, capsys) -> None:
    calls: list[str] = []
    monkeypatch.setattr(operator_setup, "Settings", lambda: object())
    monkeypatch.setattr(operator_setup, "AlembicConfig", lambda _: object())
    monkeypatch.setattr(
        operator_setup.alembic_command,
        "upgrade",
        lambda _, revision: calls.append(revision),
    )
    monkeypatch.setattr(
        operator_setup,
        "AlembicMigrationStateGate",
        lambda _: SimpleNamespace(check=lambda: GateResult("migration-state", True, "At head.")),
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "migrate"])

    assert cli.main() == 0
    assert calls == ["head"]
    assert json.loads(capsys.readouterr().out)["status"] == "applied"


def test_failed_readiness_prevents_immediate_poll_mutation(monkeypatch, capsys) -> None:
    monkeypatch.setattr(operator_runtime, "Settings", lambda: object())
    monkeypatch.setattr(
        operator_runtime,
        "phase_one_startup_gates",
        lambda _: (SimpleNamespace(check=lambda: GateResult("bootstrap", False, "Not ready.")),),
    )
    monkeypatch.setattr(
        operator_runtime,
        "create_database_engine",
        lambda _: (_ for _ in ()).throw(AssertionError("poll must not create work")),
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "poll-now"])

    assert cli.main() == 2
    assert json.loads(capsys.readouterr().out)["failed_gate_names"] == ["bootstrap"]


def test_immediate_poll_reports_reused_scheduled_identity(monkeypatch, capsys) -> None:
    run_id, dispatch_id = UUID(int=1), UUID(int=2)
    engine = SimpleNamespace(dispose=lambda: None)
    monkeypatch.setattr(operator_runtime, "Settings", lambda: SimpleNamespace(database_url="test"))
    monkeypatch.setattr(
        operator_runtime,
        "phase_one_startup_gates",
        lambda _: (SimpleNamespace(check=lambda: GateResult("ready", True, "Ready.")),),
    )
    monkeypatch.setattr(operator_runtime, "create_database_engine", lambda _: engine)
    monkeypatch.setattr(operator_runtime, "consumers_ready", lambda _: True)
    monkeypatch.setattr(operator_runtime, "create_session_factory", lambda _: object())
    monkeypatch.setattr(operator_runtime, "ConfiguredModelReleaseVerifier", lambda _: object())
    monkeypatch.setattr(
        operator_runtime,
        "SqlAlchemyIngestionTransactions",
        lambda *_, **__: SimpleNamespace(
            get_ingestion_run=lambda _: SimpleNamespace(trigger_type="scheduled")
        ),
    )
    monkeypatch.setattr(
        operator_runtime,
        "ScheduleIngestionPoll",
        lambda *_, **__: SimpleNamespace(
            execute=lambda: RunDispatchResult(run_id, dispatch_id, False)
        ),
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "poll-now"])

    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out) == {
        "action": "poll-now",
        "status": "reused",
        "run_id": str(run_id),
        "dispatch_id": str(dispatch_id),
        "trigger_type": "scheduled",
    }


def test_direct_immediate_poll_requires_consumers(monkeypatch, capsys) -> None:
    monkeypatch.setattr(operator_runtime, "Settings", lambda: object())
    monkeypatch.setattr(
        operator_runtime,
        "phase_one_startup_gates",
        lambda _: (SimpleNamespace(check=lambda: GateResult("ready", True, "Ready.")),),
    )
    monkeypatch.setattr(operator_runtime, "consumers_ready", lambda _: False)
    monkeypatch.setattr(
        operator_runtime,
        "create_database_engine",
        lambda _: (_ for _ in ()).throw(AssertionError("poll must not create work")),
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "poll-now"])

    assert cli.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "action": "poll-now",
        "status": "not_ready",
        "reason": "consumer_unhealthy",
    }


def test_consumer_probe_rejects_stale_dispatcher_process(monkeypatch, tmp_path: Path) -> None:
    marker = tmp_path / "scan"
    marker.write_text("1234", encoding="ascii")
    monkeypatch.setattr(operator_runtime, "SCAN_HEALTH_MARKER", marker)
    monkeypatch.setattr(
        operator_runtime.os, "kill", lambda *_: (_ for _ in ()).throw(ProcessLookupError())
    )
    consuming = [True]
    monkeypatch.setattr(operator_runtime, "ingestor_consuming", lambda _: consuming[0])
    settings = SimpleNamespace(dispatcher_poll_interval_seconds=5)

    assert operator_runtime.consumers_ready(settings) is False
    monkeypatch.setattr(operator_runtime.os, "kill", lambda *_: None)
    consuming[0] = False
    assert operator_runtime.consumers_ready(settings) is False
    consuming[0] = True
    assert operator_runtime.consumers_ready(settings) is True


def test_worker_health_rejects_missing_migration(monkeypatch, capsys) -> None:
    monkeypatch.setattr(operator_runtime, "Settings", lambda: object())
    monkeypatch.setattr(
        operator_runtime,
        "PostgresConnectivityHealthCheck",
        lambda _: SimpleNamespace(check=lambda: GateResult("postgres", True, "Ready.")),
    )
    monkeypatch.setattr(
        operator_runtime,
        "RedisConnectivityHealthCheck",
        lambda _: SimpleNamespace(check=lambda: GateResult("redis", True, "Ready.")),
    )
    monkeypatch.setattr(
        operator_runtime,
        "AlembicMigrationStateGate",
        lambda _: SimpleNamespace(check=lambda: GateResult("migration", False, "Missing.")),
    )
    monkeypatch.setattr(operator_runtime, "ingestor_consuming", lambda *_, **__: True)
    monkeypatch.setattr(sys, "argv", ["quakestrike", "health-ingestor"])

    assert cli.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "unhealthy"


def test_compose_orders_consumers_before_healthy_beat() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI unavailable")
    root = Path(__file__).resolve().parents[3]
    image_tag = "a" * 40
    result = subprocess.run(
        [
            docker,
            "compose",
            "--env-file",
            ".env.example",
            "-f",
            "infrastructure/compose.yml",
            "-f",
            "infrastructure/compose.release.yml",
            "--profile",
            "beat",
            "--profile",
            "init",
            "config",
            "--format",
            "json",
        ],
        cwd=root,
        env={**os.environ, "WORKER_IMAGE_TAG": image_tag},
        capture_output=True,
        text=True,
        check=True,
    )
    services = json.loads(result.stdout)["services"]
    beat = services["beat"]
    assert beat["depends_on"]["dispatcher"]["condition"] == "service_healthy"
    assert beat["depends_on"]["data-ingestor"]["condition"] == "service_healthy"
    assert beat["restart"] == "no"
    assert "health-beat" in beat["healthcheck"]["test"]
    assert "health-dispatcher" in services["dispatcher"]["healthcheck"]["test"]
    assert "health-ingestor" in services["data-ingestor"]["healthcheck"]["test"]
    assert all(
        services[name]["mem_limit"] == "536870912"
        for name in ("dispatcher", "data-ingestor", "beat")
    )
    assert "quakestrike_migration" in services["release-init"]["environment"]["DATABASE_URL"]
    assert all(
        "quakestrike_worker" in services[name]["environment"]["DATABASE_URL"]
        for name in ("dispatcher", "data-ingestor", "beat")
    )
    assert all(
        services[name]["image"] == f"quakestrike-workers:{image_tag}"
        for name in ("release-init", "dispatcher", "data-ingestor", "beat")
    )
    assert all(
        "build" not in services[name]
        for name in ("release-init", "dispatcher", "data-ingestor", "beat")
    )


@pytest.mark.parametrize(
    ("dirty", "existing_revision", "expected_reason"),
    [
        (True, None, "checkout_not_clean"),
        (False, "different", "tag_already_exists_with_different_source"),
    ],
)
def test_image_build_rejects_dirty_or_overwritten_tag(
    dirty: bool, existing_revision: str | None, expected_reason: str
) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell unavailable")
    root = Path(__file__).resolve().parents[3]
    script = root / "infrastructure" / "scripts" / "build-worker-image.ps1"
    commit = "a" * 40
    status = "' M README.md'" if dirty else "return"
    inspect = "'different'" if existing_revision else "return"
    command = (
        f"function git {{ if ($args -contains 'status') {{ $global:LASTEXITCODE = 0; {status} }} "
        f"else {{ $global:LASTEXITCODE = 0; '{commit}' }} }}; "
        "function docker { "
        "if ($args -contains 'config') { $global:LASTEXITCODE = 0; "
        f"'quakestrike-workers:{commit}'; return }}; "
        f"if ($args -contains 'inspect') {{ $global:LASTEXITCODE = 0; {inspect}; return }}; "
        "throw 'build must not run' }; "
        f"& '{script.as_posix()}'"
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert json.loads(result.stdout)["reason"] == expected_reason


def test_image_build_uses_the_clean_matching_commit(tmp_path: Path) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell unavailable")
    root = Path(__file__).resolve().parents[3]
    script = root / "infrastructure" / "scripts" / "build-worker-image.ps1"
    trace = tmp_path / "build.log"
    commit = "a" * 40
    command = (
        "function git { if ($args -contains 'status') { $global:LASTEXITCODE = 0; return }; "
        f"$global:LASTEXITCODE = 0; '{commit}' }}; "
        "function docker { "
        "if ($args -contains 'config') { $global:LASTEXITCODE = 0; "
        f"'quakestrike-workers:{commit}'; return }}; "
        "if ($args -contains 'inspect') { $global:LASTEXITCODE = 1; return }; "
        f"Add-Content -LiteralPath '{trace.as_posix()}' -Value ($args -join ','); "
        "$global:LASTEXITCODE = 0; 'image-id' }; "
        f"& '{script.as_posix()}'"
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "action": "build-worker-image",
        "status": "built",
        "commit": commit,
    }
    assert f"org.opencontainers.image.revision={commit}" in trace.read_text(encoding="utf-8")


@pytest.mark.parametrize("failure", ["startup", "health"])
def test_enable_beat_reports_failure_without_success(failure: str) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell unavailable")
    root = Path(__file__).resolve().parents[3]
    script = root / "infrastructure" / "scripts" / "enable-beat.ps1"
    up_exit = 1 if failure == "startup" else 0
    inspect_result = "'true|unhealthy'" if failure == "health" else "'true|healthy'"
    command = (
        "function docker { "
        "if ($args -contains 'inspect') { $global:LASTEXITCODE = 0; "
        f"if ($args -contains 'beat-container') {{ {inspect_result} }} "
        "else { 'true|healthy' }; return }; "
        f"if ($args -contains 'up') {{ $global:LASTEXITCODE = {up_exit}; return }}; "
        "if ($args -contains 'beat') { $global:LASTEXITCODE = 0; 'beat-container'; return }; "
        "$global:LASTEXITCODE = 0; 'test-container' }; "
        f"& '{script.as_posix()}'"
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert '"status":"failed"' in result.stdout
    assert '"status":"enabled"' not in result.stdout


def test_enable_beat_stops_when_consumer_fails_during_start(tmp_path: Path) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell unavailable")
    root = Path(__file__).resolve().parents[3]
    script = root / "infrastructure" / "scripts" / "enable-beat.ps1"
    trace = tmp_path / "docker.log"
    command = (
        "$script:started = $false; "
        "function docker { "
        f"Add-Content -LiteralPath '{trace.as_posix()}' -Value ($args -join ','); "
        "if ($args -contains 'up') { $script:started = $true; $global:LASTEXITCODE = 0; "
        "return }; "
        "if ($args -contains 'inspect') { $global:LASTEXITCODE = 0; "
        "if ($script:started -and -not ($args -contains 'beat-container')) { "
        "'true|unhealthy' } else { 'true|healthy' }; return }; "
        "if ($args -contains 'beat') { $global:LASTEXITCODE = 0; 'beat-container'; "
        "return }; "
        "$global:LASTEXITCODE = 0; 'test-container' }; "
        f"& '{script.as_posix()}'"
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert '"reason":"consumer_unhealthy"' in result.stdout
    assert '"status":"enabled"' not in result.stdout
    calls = trace.read_text(encoding="utf-8")
    assert "stop,beat" in calls
    assert "--no-deps" not in calls


def test_poll_now_runs_in_dispatcher_container() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell unavailable")
    root = Path(__file__).resolve().parents[3]
    script = root / "infrastructure" / "scripts" / "poll-now.ps1"
    command = (
        "function docker { "
        "if ($args -contains 'inspect') { $global:LASTEXITCODE = 0; 'true|healthy'; return }; "
        "if ($args -contains 'exec') { $global:LASTEXITCODE = 0; "
        "'EXEC:' + ($args -join ','); return }; "
        "$global:LASTEXITCODE = 0; 'test-container' }; "
        f"& '{script.as_posix()}'"
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "exec,-T,dispatcher,uv,run,--frozen,--no-dev,--no-sync,quakestrike,poll-now" in result.stdout
