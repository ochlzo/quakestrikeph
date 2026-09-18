from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from quakestrike.infrastructure.models.release_manifest import (  # type: ignore[import-not-found]
    TRACKED_RELEASE_MANIFEST,
    ManifestValidationError,
    load_verified_release_manifest,
)

RELEASE_ID = UUID("2f532893-7a25-4f18-814c-91d66f38dac4")


def test_reviewed_production_policy_has_fixed_canonical_bytes_and_provenance() -> None:
    raw = TRACKED_RELEASE_MANIFEST.read_bytes()
    document = json.loads(raw)

    assert hashlib.sha256(raw).hexdigest() == (
        "39e1808fac8c511d02b84c3f7f1c2787e7237a152c29daf0c1c23e156481dc0f"
    )
    assert raw == json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert len(document["artifacts"]) == 8
    assert document["provenance"]["source_policy"] == {
        "schema_version": 3,
        "mode": "exploratory",
        "primary_weighting": "anchor",
        "secondary_policy": "guard",
        "baseline": "stratified-baseline-02",
        "band_bounds": "lower inclusive, upper exclusive; do not round input magnitudes",
    }
    assert {
        target["source_metadata"]["model_name"]
        for route in document["routes"].values()
        for target in route["targets"]
    } == {"lightgbm", "catboost"}


def _manifest() -> dict[str, object]:
    artifact_bytes = b"known-good-model-bytes\n"
    artifact_hash = hashlib.sha256(artifact_bytes).hexdigest()
    return {
        "schema_version": "quakestrike.model-release.v1",
        "release_id": str(RELEASE_ID),
        "version_label": "SEIS 1.0",
        "input_schema_version": "quakestrike.prediction-input.v1",
        "output_schema_version": "quakestrike.prediction-output.v1",
        "provenance": {
            "package_name": "balanced-selection-anchor-exploratory-01",
            "package_status": "provisional_development_exception",
            "deployment_authorized": False,
            "path_base": "training_project_root",
            "registry_sha256": "a" * 64,
            "routes_sha256": "b" * 64,
            "source_package": "baselines/attempt-2/stratified-baseline-02/chosen-models/example",
            "source_policy": {
                "schema_version": 3,
                "mode": "exploratory",
                "primary_weighting": "anchor",
                "secondary_policy": "guard",
                "baseline": "stratified-baseline-02",
                "band_bounds": "lower inclusive",
            },
        },
        "postprocessing": {"maximum": "Sort quantiles then floor at M1.0."},
        "routes": {
            "probability": {
                "default_model": "lightgbm",
                "route_metadata": {
                    "models": ["lightgbm"],
                    "outside_ranges": "use_default_with_limited_evidence",
                    "overrides": [],
                    "qualified": False,
                    "status": "test",
                },
                "targets": [
                    {
                        "name": "m1_probability",
                        "target": "m1_plus_occurred_24h",
                        "kind": "binary",
                        "features": ["anchor_magnitude"],
                        "artifact_path": "models/m1_probability.txt",
                        "source_metadata": {
                            "model_name": "lightgbm",
                            "alpha": None,
                            "best_rounds": 1,
                            "provenance": {},
                            "source_file": "weights/model.txt",
                            "source_model_index": "model_index.json",
                            "validation_metrics": "metrics.json",
                        },
                    }
                ],
            }
        },
        "artifacts": [{"path": "models/m1_probability.txt", "sha256": artifact_hash}],
    }


def _write_bundle(root: Path, manifest: dict[str, object] | None = None) -> Path:
    bundle = root / "seis-1.0"
    artifact = bundle / "models" / "m1_probability.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"known-good-model-bytes\n")
    manifest_path = bundle / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest or _manifest(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return manifest_path


def test_loads_a_verified_manifest_and_hashes_its_exact_canonical_bytes(tmp_path: Path) -> None:
    manifest_path = _write_bundle(tmp_path)
    expected_bytes = manifest_path.read_bytes()

    release = load_verified_release_manifest(tmp_path, "seis-1.0/manifest.json")

    assert release.release_id == RELEASE_ID
    assert release.manifest_hash == hashlib.sha256(expected_bytes).hexdigest()
    assert release.artifact_paths == ("models/m1_probability.txt",)
    assert release.artifact_hashes == {
        "models/m1_probability.txt": hashlib.sha256(b"known-good-model-bytes\n").hexdigest()
    }


def test_rejects_a_changed_artifact_before_returning_a_release(tmp_path: Path) -> None:
    manifest_path = _write_bundle(tmp_path)
    (manifest_path.parent / "models" / "m1_probability.txt").write_bytes(b"changed")

    with pytest.raises(ManifestValidationError, match="artifact hash"):
        load_verified_release_manifest(tmp_path, "seis-1.0/manifest.json")


def test_rejects_an_unsafe_manifest_uri_before_opening_a_file(tmp_path: Path) -> None:
    with pytest.raises(ManifestValidationError, match="relative"):
        load_verified_release_manifest(tmp_path, "../manifest.json")


@pytest.mark.parametrize(
    "case",
    [
        "missing_field",
        "unknown_field",
        "wrong_schema",
        "bad_hash_syntax",
        "bad_provenance_hash",
        "empty_provenance",
        "empty_route_metadata",
        "empty_source_metadata",
        "empty_routes",
        "empty_targets",
        "duplicate_target",
        "duplicate_feature",
        "whitespace_feature",
        "absolute_artifact",
        "traversal_artifact",
        "backslash_artifact",
        "alias_artifact",
        "case_colliding_artifact",
        "unused_artifact",
        "reused_artifact",
        "case_colliding_route",
    ],
)
def test_rejects_malformed_public_manifest(tmp_path: Path, case: str) -> None:
    document = _manifest()
    provenance = document["provenance"]
    routes = document["routes"]
    route = routes["probability"]
    target = route["targets"][0]
    artifacts = document["artifacts"]
    if case == "missing_field":
        del document["version_label"]
    elif case == "unknown_field":
        document["unknown"] = True
    elif case == "wrong_schema":
        document["schema_version"] = "later"
    elif case == "bad_hash_syntax":
        artifacts[0]["sha256"] = "BAD"
    elif case == "bad_provenance_hash":
        provenance["routes_sha256"] = "BAD"
    elif case == "empty_provenance":
        document["provenance"] = {}
    elif case == "empty_route_metadata":
        route["route_metadata"] = {}
    elif case == "empty_source_metadata":
        target["source_metadata"] = {}
    elif case == "empty_routes":
        document["routes"] = {}
    elif case == "empty_targets":
        route["targets"] = []
    elif case == "duplicate_target":
        route["targets"].append(target.copy())
    elif case == "duplicate_feature":
        target["features"].append("anchor_magnitude")
    elif case == "whitespace_feature":
        target["features"] = [" anchor_magnitude "]
    elif case == "absolute_artifact":
        artifacts[0]["path"] = "C:/outside/model.txt"
    elif case == "traversal_artifact":
        artifacts[0]["path"] = "../outside/model.txt"
    elif case == "backslash_artifact":
        artifacts[0]["path"] = r"models\m1_probability.txt"
    elif case == "alias_artifact":
        artifacts[0]["path"] = "models/CON.txt"
    elif case == "case_colliding_artifact":
        artifacts.append({"path": "Models/m1_probability.txt", "sha256": artifacts[0]["sha256"]})
    elif case == "unused_artifact":
        artifacts.append({"path": "models/unused.txt", "sha256": artifacts[0]["sha256"]})
        extra = tmp_path / "seis-1.0" / "models" / "unused.txt"
        extra.parent.mkdir(parents=True)
        extra.write_bytes(b"known-good-model-bytes\n")
    elif case == "reused_artifact":
        route["targets"].append({**target, "name": "another"})
    elif case == "case_colliding_route":
        routes["Probability"] = route.copy()

    _write_bundle(tmp_path, document)
    with pytest.raises(ManifestValidationError):
        load_verified_release_manifest(tmp_path, "seis-1.0/manifest.json")


def test_rejects_missing_artifact(tmp_path: Path) -> None:
    manifest = _write_bundle(tmp_path)
    (manifest.parent / "models" / "m1_probability.txt").unlink()
    with pytest.raises(ManifestValidationError):
        load_verified_release_manifest(tmp_path, "seis-1.0/manifest.json")


def test_rejects_artifact_symlink_escape(tmp_path: Path) -> None:
    manifest = _write_bundle(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"known-good-model-bytes\n")
    artifact = manifest.parent / "models" / "m1_probability.txt"
    artifact.unlink()
    try:
        artifact.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is unavailable")
    with pytest.raises(ManifestValidationError):
        load_verified_release_manifest(tmp_path, "seis-1.0/manifest.json")
