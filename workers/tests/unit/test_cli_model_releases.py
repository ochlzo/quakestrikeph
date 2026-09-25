from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError

from quakestrike import cli, operator_setup
from quakestrike.application.startup import GateResult
from quakestrike.infrastructure.models.release_manifest import (
    ManifestValidationError,
    VerifiedReleaseManifest,
    model_release_record,
)


class _Settings:
    model_release_id = UUID("a7f2286b-13a2-4708-a04d-4139281a4e1f")
    model_artifact_directory = Path("model-artifacts")
    database_url = "postgresql+psycopg://worker:secret@postgres:5432/quakestrike"


def verified_manifest() -> VerifiedReleaseManifest:
    return VerifiedReleaseManifest(
        _Settings.model_release_id,
        "SEIS 1.0.1",
        "input.v1",
        "output.v2",
        "seis-1.0.1/manifest.json",
        "a" * 64,
        (),
    )


class TrackingEngine:
    disposed = False

    def dispose(self) -> None:
        self.disposed = True


def test_historical_recovery_requires_full_bootstrap_readiness(monkeypatch, capsys):
    monkeypatch.setattr(operator_setup, "Settings", _Settings)

    def gate(ready):
        return lambda _: SimpleNamespace(check=lambda: GateResult("gate", ready, "checked", {}))

    monkeypatch.setattr(operator_setup, "AlembicMigrationStateGate", gate(True))
    monkeypatch.setattr(operator_setup, "ModelReleaseStartupGate", gate(True))
    monkeypatch.setattr(operator_setup, "BootstrapReadinessStartupGate", gate(False))
    monkeypatch.setattr(
        operator_setup,
        "load_run_manifest",
        lambda _: pytest.fail("Recovery read the manifest after readiness failed."),
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "recover-historical-predictions"])

    assert cli.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "rejected"


def test_package_command_dispatches_to_the_explicit_packager(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Path] = {}
    monkeypatch.setattr(operator_setup, "Settings", _Settings)
    monkeypatch.setattr(
        operator_setup,
        "package_selected_release",
        lambda source, destination: captured.update(source=source, destination=destination),
    )
    monkeypatch.setattr(
        sys, "argv", ["quakestrike", "package-model-release", "--source-package", str(tmp_path)]
    )

    assert cli.main() == 0
    assert captured == {"source": tmp_path, "destination": Path("model-artifacts")}


def test_register_command_rejects_a_manifest_with_the_wrong_configured_id(monkeypatch) -> None:
    monkeypatch.setattr(operator_setup, "Settings", _Settings)
    monkeypatch.setattr(
        operator_setup,
        "load_verified_release_manifest",
        lambda *_, **__: VerifiedReleaseManifest(
            UUID("00000000-0000-0000-0000-000000000001"),
            "SEIS 1.0",
            "input.v1",
            "output.v1",
            "seis-1.0/manifest.json",
            "a" * 64,
            (),
        ),
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "register-model-release"])

    assert cli.main() == 2


def test_register_command_registers_the_verified_release_and_disposes_the_engine(
    monkeypatch,
) -> None:
    manifest = verified_manifest()
    engine = TrackingEngine()
    captured: dict[str, object] = {}
    monkeypatch.setattr(operator_setup, "Settings", _Settings)
    monkeypatch.setattr(
        operator_setup,
        "load_verified_release_manifest",
        lambda directory, uri, **_: captured.update(directory=directory, uri=uri) or manifest,
    )
    monkeypatch.setattr(
        operator_setup, "create_database_engine", lambda url: captured.update(url=url) or engine
    )
    monkeypatch.setattr(operator_setup, "create_session_factory", lambda received: received)
    monkeypatch.setattr(
        operator_setup,
        "SqlAlchemyModelReleaseRegistry",
        lambda _: type(
            "Registry",
            (),
            {"register": lambda self, release: captured.update(release=release) or True},
        )(),
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "register-model-release"])

    assert cli.main() == 0
    assert captured == {
        "directory": Path("model-artifacts"),
        "uri": "seis-1.0.1/manifest.json",
        "url": _Settings.database_url,
        "release": model_release_record(manifest),
    }
    assert engine.disposed is True


@pytest.mark.parametrize("failure", [OSError("C:/private/source"), ValueError("secret payload")])
def test_package_command_sanitizes_expected_failures(
    monkeypatch, tmp_path: Path, capsys, failure: Exception
) -> None:
    monkeypatch.setattr(operator_setup, "Settings", _Settings)
    monkeypatch.setattr(
        operator_setup, "package_selected_release", lambda *_: (_ for _ in ()).throw(failure)
    )
    monkeypatch.setattr(
        sys, "argv", ["quakestrike", "package-model-release", "--source-package", str(tmp_path)]
    )
    assert cli.main() == 2
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "failed"
    assert "C:/private/source" not in output
    assert "secret payload" not in output
    assert "Traceback" not in output


def test_registration_conflict_disposes_engine_and_sanitizes_error(monkeypatch, capsys) -> None:
    engine = TrackingEngine()
    monkeypatch.setattr(operator_setup, "Settings", _Settings)
    monkeypatch.setattr(
        operator_setup, "load_verified_release_manifest", lambda *_, **__: verified_manifest()
    )
    monkeypatch.setattr(operator_setup, "create_database_engine", lambda _: engine)
    monkeypatch.setattr(operator_setup, "create_session_factory", lambda received: received)
    monkeypatch.setattr(
        operator_setup,
        "SqlAlchemyModelReleaseRegistry",
        lambda _: type(
            "Registry",
            (),
            {"register": lambda self, release: (_ for _ in ()).throw(ValueError("secret SQL"))},
        )(),
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "register-model-release"])
    assert cli.main() == 2
    assert engine.disposed is True
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "failed"
    assert "secret SQL" not in output
    assert "Traceback" not in output


def test_package_cli_reports_malformed_source_without_traceback(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    package = tmp_path / "selected"
    package.mkdir()
    (package / "routes.json").write_text('{"routes":{"probability":{}}}', encoding="utf-8")
    monkeypatch.setattr(operator_setup, "Settings", _Settings)
    monkeypatch.setattr(
        sys, "argv", ["quakestrike", "package-model-release", "--source-package", str(package)]
    )

    assert cli.main() == 2

    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "failed"
    assert "Traceback" not in output
    assert str(package) not in output


@pytest.mark.parametrize(
    "failure",
    [
        ManifestValidationError("missing manifest /secret"),
        ManifestValidationError("changed artifact /secret"),
        OSError("missing artifact /secret"),
    ],
)
def test_register_cli_sanitizes_expected_bundle_failures(
    monkeypatch, capsys, failure: Exception
) -> None:
    monkeypatch.setattr(operator_setup, "Settings", _Settings)
    monkeypatch.setattr(
        operator_setup,
        "load_verified_release_manifest",
        lambda *_, **__: (_ for _ in ()).throw(failure),
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "register-model-release"])

    assert cli.main() == 2

    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "failed"
    assert "/secret" not in output
    assert "Traceback" not in output


def test_register_cli_disposes_engine_on_database_failure(monkeypatch, capsys) -> None:
    engine = TrackingEngine()
    monkeypatch.setattr(operator_setup, "Settings", _Settings)
    monkeypatch.setattr(
        operator_setup, "load_verified_release_manifest", lambda *_, **__: verified_manifest()
    )
    monkeypatch.setattr(operator_setup, "create_database_engine", lambda _: engine)
    monkeypatch.setattr(operator_setup, "create_session_factory", lambda received: received)
    monkeypatch.setattr(
        operator_setup,
        "SqlAlchemyModelReleaseRegistry",
        lambda _: type(
            "Registry",
            (),
            {
                "register": lambda self, release: (_ for _ in ()).throw(
                    OperationalError("SELECT secret", {}, Exception("private database"))
                )
            },
        )(),
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "register-model-release"])

    assert cli.main() == 2

    assert engine.disposed is True
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "failed"
    assert "secret" not in output
    assert "private database" not in output


@pytest.mark.parametrize("command", ["config-check"])
def test_existing_read_only_commands_still_delegate_to_service_runtime(
    monkeypatch, command: str
) -> None:
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        cli,
        "run_service",
        lambda service, *, command: captured.update(service=service, command=command) or 7,
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", command])

    assert cli.main() == 7
    assert captured == {"service": "cli", "command": command}


def test_startup_check_writes_json_readiness_to_manifest_and_stdout(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    manifest_path = tmp_path / "bootstrap-readiness.json"
    settings = type(
        "StartupSettings",
        (),
        {"bootstrap_run_manifest": manifest_path, "log_level": "INFO"},
    )()

    class Gate:
        def __init__(self, name: str, ready: bool = True) -> None:
            self.name = name
            self.ready = ready

        def check(self):  # type: ignore[no-untyped-def]
            details = {}
            if self.name == "model-release" and self.ready:
                details = {
                    "release_id": str(UUID(int=1)),
                    "version_label": "SEIS 1.0",
                    "manifest_uri": "seis-1.0/manifest.json",
                    "manifest_hash": "a" * 64,
                    "input_schema_version": "input.v1",
                    "output_schema_version": "output.v1",
                    "artifact_hashes": '{"model.bin": "bbbb"}',
                }
            return GateResult(
                name=self.name,
                ready=self.ready,
                reason="ready" if self.ready else "not ready",
                details=details,
            )

    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "phase_one_startup_gates",
        lambda _settings: tuple(
            Gate(name)
            for name in (
                "migration-state",
                "model-release",
                "bootstrap-readiness",
                "postgres-connectivity",
                "redis-connectivity",
            )
        ),
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "startup-check"])

    assert cli.main() == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert output["ready"] is True
    assert output["failed_gate_names"] == []
    assert manifest["readiness"]["ready"] is True
    assert manifest["readiness"]["model_release"]["version_label"] == "SEIS 1.0"
    assert captured.err != ""


def test_startup_check_returns_two_and_records_failed_gate(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    settings = type(
        "StartupSettings",
        (),
        {"bootstrap_run_manifest": tmp_path / "bootstrap-readiness.json", "log_level": "INFO"},
    )()

    class FailedGate:
        name = "redis-connectivity"

        def check(self):  # type: ignore[no-untyped-def]
            return GateResult(
                name=self.name,
                ready=False,
                reason="Redis connectivity is unavailable.",
            )

    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "phase_one_startup_gates", lambda _settings: (FailedGate(),))
    monkeypatch.setattr(sys, "argv", ["quakestrike", "startup-check"])

    assert cli.main() == 2
    capsys.readouterr()
    manifest = json.loads(settings.bootstrap_run_manifest.read_text(encoding="utf-8"))
    assert manifest["readiness"]["ready"] is False
    assert manifest["readiness"]["failed_gate_names"] == ["redis-connectivity"]


def test_startup_check_preserves_invalid_bootstrap_manifest(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    manifest_path = tmp_path / "bootstrap-readiness.json"
    manifest_path.write_text("not json", encoding="utf-8")
    settings = type(
        "StartupSettings",
        (),
        {"bootstrap_run_manifest": manifest_path, "log_level": "INFO"},
    )()

    class FailedGate:
        name = "bootstrap-readiness"

        def check(self):  # type: ignore[no-untyped-def]
            return GateResult(name=self.name, ready=False, reason="evidence is invalid")

    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "phase_one_startup_gates", lambda _settings: (FailedGate(),))
    monkeypatch.setattr(sys, "argv", ["quakestrike", "startup-check"])

    assert cli.main() == 2
    output = json.loads(capsys.readouterr().out)
    assert output["ready"] is False
    assert output["failed_gate_names"] == ["bootstrap-readiness", "readiness-manifest"]
    assert manifest_path.read_text(encoding="utf-8") == "not json"


def test_startup_check_returns_one_when_readiness_manifest_cannot_be_written(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    settings = type(
        "StartupSettings",
        (),
        {"bootstrap_run_manifest": tmp_path / "bootstrap-readiness.json", "log_level": "INFO"},
    )()

    class ReadyGate:
        name = "migration-state"

        def check(self):  # type: ignore[no-untyped-def]
            return GateResult(name=self.name, ready=True, reason="ready")

    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "phase_one_startup_gates", lambda _settings: (ReadyGate(),))
    monkeypatch.setattr(
        cli,
        "write_startup_readiness_manifest",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("private path")),
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "startup-check"])

    assert cli.main() == 1
    output = json.loads(capsys.readouterr().out)
    assert output == {"reason": "startup check failed", "status": "failed"}
