from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError

from quakestrike.application.startup import evaluate_startup_gates
from quakestrike.domain.features import INPUT_SCHEMA_VERSION
from quakestrike.infrastructure import startup
from quakestrike.infrastructure.models import release_manifest
from quakestrike.infrastructure.models.release_manifest import (
    TRACKED_RELEASE_MANIFEST,
    VerifiedReleaseManifest,
    model_release_record,
)
from quakestrike.infrastructure.models.seis import OUTPUT_SCHEMA_VERSION
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import (
    BootstrapReadinessStartupGate,
    ModelReleaseStartupGate,
    UnavailableStartupGate,
    phase_one_startup_gates,
)


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


def verified_manifest(settings: Settings) -> VerifiedReleaseManifest:
    return VerifiedReleaseManifest(
        release_id=settings.model_release_id,
        version_label="SEIS 1.0.1",
        input_schema_version=INPUT_SCHEMA_VERSION,
        output_schema_version=OUTPUT_SCHEMA_VERSION,
        manifest_uri="seis-1.0.1/manifest.json",
        manifest_hash="a" * 64,
        artifact_paths=("models/example.bin",),
        artifact_hashes={"models/example.bin": "b" * 64},
    )


class TrackingEngine:
    disposed = False

    def dispose(self) -> None:
        self.disposed = True


def test_phase_one_gates_fail_closed_and_report_sanitized_details() -> None:
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


def test_startup_report_evaluates_remaining_gates_after_one_gate_raises() -> None:
    class FailingGate:
        name = "failing"

        def check(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("private connection details")

    class ReadyGate:
        name = "ready"

        def check(self):  # type: ignore[no-untyped-def]
            return startup.GateResult(name=self.name, ready=True, reason="ready")

    report = evaluate_startup_gates((FailingGate(), ReadyGate()))

    assert report.ready is False
    assert report.failed_gate_names == ("failing",)
    assert report.results[0].reason == "Startup gate failed safely."
    assert report.results[0].details == {"error_type": "RuntimeError"}
    assert report.results[1].ready is True


def test_model_release_gate_is_not_ready_when_the_registered_row_differs(
    monkeypatch,
) -> None:
    settings = valid_settings()
    manifest = verified_manifest(settings)
    engine = TrackingEngine()
    stored = replace(model_release_record(manifest), artifact_manifest_hash="b" * 64)
    monkeypatch.setattr(startup, "load_verified_release_manifest", lambda *_, **__: manifest)
    monkeypatch.setattr(startup, "create_database_engine", lambda _: engine)
    monkeypatch.setattr(startup, "create_session_factory", lambda received: received)
    monkeypatch.setattr(
        startup,
        "SqlAlchemyModelReleaseRegistry",
        lambda _: type("Registry", (), {"get": lambda self, release_id: stored})(),
    )

    result = ModelReleaseStartupGate(settings).check()

    assert result.ready is False
    assert result.reason == "Model release verification failed."
    assert engine.disposed is True


def test_model_release_gate_rejects_a_non_selected_release(monkeypatch) -> None:
    settings = valid_settings()
    manifest = replace(verified_manifest(settings), version_label="SEIS 0.9")
    monkeypatch.setattr(startup, "load_verified_release_manifest", lambda *_, **__: manifest)
    monkeypatch.setattr(
        startup,
        "create_database_engine",
        lambda _: (_ for _ in ()).throw(AssertionError("database reached")),
    )

    result = ModelReleaseStartupGate(settings).check()

    assert result.ready is False
    assert result.reason == "Model release verification failed."


def test_model_release_gate_rejects_an_unsupported_output_contract(monkeypatch) -> None:
    settings = valid_settings()
    manifest = replace(verified_manifest(settings), output_schema_version="output.v1")
    monkeypatch.setattr(startup, "load_verified_release_manifest", lambda *_, **__: manifest)
    monkeypatch.setattr(
        startup,
        "create_database_engine",
        lambda _: (_ for _ in ()).throw(AssertionError("database reached")),
    )

    result = ModelReleaseStartupGate(settings).check()

    assert result.ready is False
    assert result.reason == "Model release verification failed."


def test_model_release_gate_disposes_the_engine_when_the_registry_query_fails(
    monkeypatch,
) -> None:
    settings = valid_settings()
    manifest = verified_manifest(settings)
    engine = TrackingEngine()

    def query_failure(_release_id):
        raise OperationalError("SELECT model_releases", {}, Exception("down"))

    monkeypatch.setattr(startup, "load_verified_release_manifest", lambda *_, **__: manifest)
    monkeypatch.setattr(startup, "create_database_engine", lambda _: engine)
    monkeypatch.setattr(startup, "create_session_factory", lambda received: received)
    monkeypatch.setattr(
        startup,
        "SqlAlchemyModelReleaseRegistry",
        lambda _: type(
            "Registry", (), {"get": lambda self, release_id: query_failure(release_id)}
        )(),
    )

    result = ModelReleaseStartupGate(settings).check()

    assert result.ready is False
    assert result.reason == "Model release verification failed."
    assert engine.disposed is True


@pytest.mark.parametrize(
    "damage",
    [
        "configured_id",
        "missing_manifest",
        "changed_manifest",
        "missing_artifact",
        "changed_artifact",
    ],
)
def test_startup_report_rejects_unverified_bundle_before_database_work(
    tmp_path: Path, monkeypatch, damage: str
) -> None:
    bundle = tmp_path / "seis-1.0.1"
    document = json.loads(TRACKED_RELEASE_MANIFEST.read_bytes())
    route_name, route = next(iter(document["routes"].items()))
    route["targets"] = [route["targets"][0]]
    document["routes"] = {route_name: route}
    artifact_path = route["targets"][0]["artifact_path"]
    artifact = bundle / artifact_path
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"fixture weight")
    document["artifacts"] = [
        {"path": artifact_path, "sha256": hashlib.sha256(b"fixture weight").hexdigest()}
    ]
    manifest = bundle / "manifest.json"
    manifest.write_bytes(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    )
    policy = tmp_path / "approved.json"
    policy.write_bytes(manifest.read_bytes())
    monkeypatch.setattr(release_manifest, "TRACKED_RELEASE_MANIFEST", policy)
    settings = valid_settings().model_copy(
        update={
            "model_release_id": UUID("a7f2286b-13a2-4708-a04d-4139281a4e1f"),
            "model_artifact_directory": tmp_path,
        }
    )
    if damage == "configured_id":
        settings = settings.model_copy(update={"model_release_id": UUID(int=1)})
    elif damage == "missing_manifest":
        (bundle / "manifest.json").unlink()
    elif damage == "changed_manifest":
        (bundle / "manifest.json").write_bytes(b"changed")
    elif damage == "missing_artifact":
        artifact.unlink()
    elif damage == "changed_artifact":
        artifact.write_bytes(b"changed")
    before = {
        str(path.relative_to(tmp_path)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(
        startup,
        "create_database_engine",
        lambda _: (_ for _ in ()).throw(AssertionError("database reached")),
    )

    if damage in {"changed_artifact", "missing_artifact"}:
        with pytest.raises(
            release_manifest.ManifestValidationError,
            match="artifact hash" if damage == "changed_artifact" else None,
        ):
            release_manifest.load_verified_release_manifest(
                tmp_path, "seis-1.0.1/manifest.json", require_selected_policy=True
            )

    report = evaluate_startup_gates((ModelReleaseStartupGate(settings),))

    assert report.ready is False
    assert report.failed_gate_names == ("model-release",)
    assert {
        str(path.relative_to(tmp_path)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == before


def test_startup_report_rejects_absent_registration(monkeypatch) -> None:
    settings = valid_settings()
    manifest = verified_manifest(settings)
    engine = TrackingEngine()
    monkeypatch.setattr(startup, "load_verified_release_manifest", lambda *_, **__: manifest)
    monkeypatch.setattr(startup, "create_database_engine", lambda _: engine)
    monkeypatch.setattr(startup, "create_session_factory", lambda received: received)
    monkeypatch.setattr(
        startup,
        "SqlAlchemyModelReleaseRegistry",
        lambda _: type("Registry", (), {"get": lambda self, release_id: None})(),
    )

    report = evaluate_startup_gates((ModelReleaseStartupGate(settings),))

    assert report.ready is False
    assert report.failed_gate_names == ("model-release",)
    assert engine.disposed is True


def test_bootstrap_readiness_gate_fails_safely_when_manifest_is_missing(tmp_path: Path) -> None:
    settings = valid_settings().model_copy(
        update={"bootstrap_run_manifest": tmp_path / "missing.json"}
    )

    result = BootstrapReadinessStartupGate(settings).check()

    assert result.ready is False
    assert result.reason == "Bootstrap readiness evidence is unavailable or invalid."
