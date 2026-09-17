from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from quakestrike.infrastructure.models import packaging


def _source(tmp_path: Path, *, route_name: str = "probability") -> Path:
    root = tmp_path / "training"
    package = root / "a" / "b" / "c" / "d" / "selected"
    package.mkdir(parents=True)
    weight = root / "weights" / "model.txt"
    weight.parent.mkdir()
    weight.write_bytes(b"weight")
    selected = {
        "source_model_index": "model_index.json",
        "file": "weights/model.txt",
        "features": ["anchor_magnitude"],
        "target": "m1_plus_occurred_24h",
        "kind": "binary",
        "alpha": 0.5,
        "best_rounds": 1,
        "validation_metrics": "metrics.json",
        "provenance": {},
        "sha256": hashlib.sha256(b"weight").hexdigest(),
    }
    package.joinpath("routes.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "mode": "test",
                "status": "provisional_development_exception",
                "primary_weighting": "anchor",
                "secondary_policy": "guard",
                "baseline": "test",
                "band_bounds": "lower inclusive",
                "registry_sha256": "a" * 64,
                "path_base": "training_project_root",
                "deployment_authorized": False,
                "postprocessing": {"maximum": "test"},
                "routes": {
                    route_name: {
                        "default": "lightgbm",
                        "overrides": [],
                        "status": "test",
                        "qualified": True,
                        "outside_ranges": "use_default_with_limited_evidence",
                        "models": {"lightgbm": {"m1_probability": selected}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return package


def _approve(source: Path, tmp_path: Path, monkeypatch) -> None:
    document = json.loads((source / "routes.json").read_text(encoding="utf-8"))
    normalized, _ = packaging._prepare(document, source, source.parents[4].resolve())
    policy = tmp_path / "policy.json"
    policy.write_bytes(packaging.canonical_json_bytes(normalized))
    monkeypatch.setattr(packaging, "TRACKED_RELEASE_MANIFEST", policy)


def test_policy_mismatch_preserves_previous_bundle(tmp_path: Path, monkeypatch) -> None:
    source = _source(tmp_path)
    destination = tmp_path / "artifacts"
    previous = destination / "seis-1.0"
    previous.mkdir(parents=True)
    (previous / "manifest.json").write_bytes(b"previous")
    policy = tmp_path / "policy.json"
    policy.write_bytes(b"different")
    monkeypatch.setattr(packaging, "TRACKED_RELEASE_MANIFEST", policy)

    with pytest.raises(ValueError, match="reviewed release manifest"):
        packaging.package_selected_release(source, destination)

    assert list(previous.rglob("*")) == [previous / "manifest.json"]
    assert (previous / "manifest.json").read_bytes() == b"previous"


@pytest.mark.parametrize("route_name", ["../escape", "C:\\escape", "a/b", "CON"])
def test_unsafe_route_never_writes_outside_bundle(
    tmp_path: Path, monkeypatch, route_name: str
) -> None:
    source = _source(tmp_path, route_name=route_name)
    destination = tmp_path / "artifacts"
    monkeypatch.setattr(packaging, "TRACKED_RELEASE_MANIFEST", tmp_path / "absent")

    with pytest.raises(ValueError):
        packaging.package_selected_release(source, destination)

    assert not destination.exists()


def test_approved_package_publishes_verified_bundle(tmp_path: Path, monkeypatch) -> None:
    source = _source(tmp_path)
    _approve(source, tmp_path, monkeypatch)
    destination = tmp_path / "artifacts"

    manifest = packaging.package_selected_release(source, destination)

    assert manifest.read_bytes() == packaging.TRACKED_RELEASE_MANIFEST.read_bytes()
    assert (manifest.parent / "models" / "probability" / "model.txt").read_bytes() == b"weight"


def test_staging_failure_keeps_prior_bundle(tmp_path: Path, monkeypatch) -> None:
    source = _source(tmp_path)
    _approve(source, tmp_path, monkeypatch)
    destination = tmp_path / "artifacts"
    bundle = destination / "seis-1.0"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_bytes(b"previous")
    monkeypatch.setattr(
        packaging.shutil,
        "copyfile",
        lambda *_: (_ for _ in ()).throw(OSError("copy failed")),
    )

    with pytest.raises(OSError):
        packaging.package_selected_release(source, destination)

    assert (bundle / "manifest.json").read_bytes() == b"previous"
    assert list(bundle.rglob("*")) == [bundle / "manifest.json"]


def test_failed_promotion_restores_prior_bundle(tmp_path: Path, monkeypatch) -> None:
    source = _source(tmp_path)
    _approve(source, tmp_path, monkeypatch)
    destination = tmp_path / "artifacts"
    bundle = destination / "seis-1.0"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_bytes(b"previous")
    rename = Path.rename

    def fail_stage_promotion(path: Path, target: Path) -> Path:
        if path.parent.name.startswith("seis-stage-"):
            raise OSError("promotion failed")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_stage_promotion)

    with pytest.raises(OSError):
        packaging.package_selected_release(source, destination)

    assert (bundle / "manifest.json").read_bytes() == b"previous"
    assert not list(destination.glob(".seis-1.0-backup-*"))


def test_malformed_source_reports_a_controlled_failure_without_writes(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (source / "routes.json").write_text('{"routes":{"probability":{}}}', encoding="utf-8")
    destination = tmp_path / "artifacts"

    with pytest.raises(ValueError, match="invalid structure"):
        packaging.package_selected_release(source, destination)

    assert not destination.exists()


def test_source_symlink_escape_never_publishes_bundle(tmp_path: Path) -> None:
    source = _source(tmp_path)
    weight = source.parents[4] / "weights" / "model.txt"
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"weight")
    weight.unlink()
    try:
        weight.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is unavailable")

    with pytest.raises(ValueError, match="escapes"):
        packaging.package_selected_release(source, tmp_path / "artifacts")

    assert not (tmp_path / "artifacts").exists()
