from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError

from quakestrike import cli
from quakestrike.infrastructure.models.release_manifest import (
    ManifestValidationError,
    VerifiedReleaseManifest,
    model_release_record,
)


class _Settings:
    model_release_id = UUID("2f532893-7a25-4f18-814c-91d66f38dac4")
    model_artifact_directory = Path("model-artifacts")
    database_url = "postgresql+psycopg://worker:secret@postgres:5432/quakestrike"


def verified_manifest() -> VerifiedReleaseManifest:
    return VerifiedReleaseManifest(
        _Settings.model_release_id,
        "SEIS 1.0",
        "input.v1",
        "output.v1",
        "seis-1.0/manifest.json",
        "a" * 64,
        (),
    )


class TrackingEngine:
    disposed = False

    def dispose(self) -> None:
        self.disposed = True


def test_package_command_dispatches_to_the_explicit_packager(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Path] = {}
    monkeypatch.setattr(cli, "Settings", _Settings)
    monkeypatch.setattr(
        cli,
        "package_selected_release",
        lambda source, destination: captured.update(source=source, destination=destination),
    )
    monkeypatch.setattr(
        sys, "argv", ["quakestrike", "package-model-release", "--source-package", str(tmp_path)]
    )

    assert cli.main() == 0
    assert captured == {"source": tmp_path, "destination": Path("model-artifacts")}


def test_register_command_rejects_a_manifest_with_the_wrong_configured_id(monkeypatch) -> None:
    monkeypatch.setattr(cli, "Settings", _Settings)
    monkeypatch.setattr(
        cli,
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

    with pytest.raises(SystemExit, match="2"):
        cli.main()


def test_register_command_registers_the_verified_release_and_disposes_the_engine(
    monkeypatch,
) -> None:
    manifest = verified_manifest()
    engine = TrackingEngine()
    captured: dict[str, object] = {}
    monkeypatch.setattr(cli, "Settings", _Settings)
    monkeypatch.setattr(
        cli,
        "load_verified_release_manifest",
        lambda directory, uri, **_: captured.update(directory=directory, uri=uri) or manifest,
    )
    monkeypatch.setattr(
        cli, "create_database_engine", lambda url: captured.update(url=url) or engine
    )
    monkeypatch.setattr(cli, "create_session_factory", lambda received: received)
    monkeypatch.setattr(
        cli,
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
        "uri": "seis-1.0/manifest.json",
        "url": _Settings.database_url,
        "release": model_release_record(manifest),
    }
    assert engine.disposed is True


@pytest.mark.parametrize("failure", [OSError("C:/private/source"), ValueError("secret payload")])
def test_package_command_sanitizes_expected_failures(
    monkeypatch, tmp_path: Path, capsys, failure: Exception
) -> None:
    monkeypatch.setattr(cli, "Settings", _Settings)
    monkeypatch.setattr(cli, "package_selected_release", lambda *_: (_ for _ in ()).throw(failure))
    monkeypatch.setattr(
        sys, "argv", ["quakestrike", "package-model-release", "--source-package", str(tmp_path)]
    )
    with pytest.raises(SystemExit, match="2"):
        cli.main()
    output = capsys.readouterr().err
    assert "model-release packaging failed" in output
    assert "C:/private/source" not in output
    assert "secret payload" not in output
    assert "Traceback" not in output


def test_registration_conflict_disposes_engine_and_sanitizes_error(monkeypatch, capsys) -> None:
    engine = TrackingEngine()
    monkeypatch.setattr(cli, "Settings", _Settings)
    monkeypatch.setattr(cli, "load_verified_release_manifest", lambda *_, **__: verified_manifest())
    monkeypatch.setattr(cli, "create_database_engine", lambda _: engine)
    monkeypatch.setattr(cli, "create_session_factory", lambda received: received)
    monkeypatch.setattr(
        cli,
        "SqlAlchemyModelReleaseRegistry",
        lambda _: type(
            "Registry",
            (),
            {"register": lambda self, release: (_ for _ in ()).throw(ValueError("secret SQL"))},
        )(),
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "register-model-release"])
    with pytest.raises(SystemExit, match="2"):
        cli.main()
    assert engine.disposed is True
    output = capsys.readouterr().err
    assert "model-release registration failed" in output
    assert "secret SQL" not in output
    assert "Traceback" not in output


def test_package_cli_reports_malformed_source_without_traceback(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    package = tmp_path / "selected"
    package.mkdir()
    (package / "routes.json").write_text('{"routes":{"probability":{}}}', encoding="utf-8")
    monkeypatch.setattr(cli, "Settings", _Settings)
    monkeypatch.setattr(
        sys, "argv", ["quakestrike", "package-model-release", "--source-package", str(package)]
    )

    with pytest.raises(SystemExit, match="2"):
        cli.main()

    output = capsys.readouterr().err
    assert "model-release packaging failed" in output
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
    monkeypatch.setattr(cli, "Settings", _Settings)
    monkeypatch.setattr(
        cli, "load_verified_release_manifest", lambda *_, **__: (_ for _ in ()).throw(failure)
    )
    monkeypatch.setattr(sys, "argv", ["quakestrike", "register-model-release"])

    with pytest.raises(SystemExit, match="2"):
        cli.main()

    output = capsys.readouterr().err
    assert "model-release registration failed" in output
    assert "/secret" not in output
    assert "Traceback" not in output


def test_register_cli_disposes_engine_on_database_failure(monkeypatch, capsys) -> None:
    engine = TrackingEngine()
    monkeypatch.setattr(cli, "Settings", _Settings)
    monkeypatch.setattr(cli, "load_verified_release_manifest", lambda *_, **__: verified_manifest())
    monkeypatch.setattr(cli, "create_database_engine", lambda _: engine)
    monkeypatch.setattr(cli, "create_session_factory", lambda received: received)
    monkeypatch.setattr(
        cli,
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

    with pytest.raises(SystemExit, match="2"):
        cli.main()

    assert engine.disposed is True
    output = capsys.readouterr().err
    assert "model-release registration failed" in output
    assert "secret" not in output
    assert "private database" not in output


@pytest.mark.parametrize("command", ["config-check", "startup-check"])
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
