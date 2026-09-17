"""Build the ignored local SEIS 1.0 bundle from the selected training package."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from quakestrike.infrastructure.models.relative_path import safe_relative_path
from quakestrike.infrastructure.models.release_manifest import (
    SELECTED_RELEASE_MANIFEST_URI,
    TRACKED_RELEASE_MANIFEST,
    canonical_json_bytes,
    load_verified_release_manifest,
)

SEIS_RELEASE_ID = UUID("2f532893-7a25-4f18-814c-91d66f38dac4")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def package_selected_release(source_package: Path, artifact_directory: Path) -> Path:
    """Validate the source and policy, then replace the bundle after staging it."""
    try:
        routes_document = json.loads((source_package / "routes.json").read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Selected package routes are not valid JSON.") from error
    try:
        source_root = source_package.parents[4].resolve(strict=True)
        document, copies = _prepare(routes_document, source_package, source_root)
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError("Selected package routes have invalid structure.") from error
    canonical = canonical_json_bytes(document)
    if not TRACKED_RELEASE_MANIFEST.is_file() or TRACKED_RELEASE_MANIFEST.read_bytes() != canonical:
        raise ValueError("Selected package metadata differs from the reviewed release manifest.")

    artifact_directory = artifact_directory.resolve()
    bundle = artifact_directory / PurePosixPath(SELECTED_RELEASE_MANIFEST_URI).parent
    stage_root = Path(tempfile.mkdtemp(prefix="seis-stage-", dir=artifact_directory.parent))
    stage = stage_root / bundle.name
    backup = artifact_directory / f".{bundle.name}-backup-{uuid4().hex}"
    try:
        stage.mkdir()
        for source, relative in copies:
            destination = (stage / relative).resolve()
            if not destination.is_relative_to(stage.resolve()):
                raise ValueError("Selected artifact destination escapes the bundle.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            if _sha256(destination) != _sha256(source):
                raise ValueError("A staged artifact differs from its source.")
        (stage / "manifest.json").write_bytes(canonical)
        load_verified_release_manifest(stage_root, f"{stage.name}/manifest.json")
        artifact_directory.mkdir(parents=True, exist_ok=True)
        had_bundle = bundle.exists()
        if had_bundle:
            bundle.rename(backup)
        try:
            stage.rename(bundle)
        except OSError:
            if had_bundle:
                backup.rename(bundle)
            raise
        if had_bundle:
            shutil.rmtree(backup, ignore_errors=True)
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    return bundle / "manifest.json"


def _safe_relative(value: object, subject: str) -> PurePosixPath:
    try:
        return safe_relative_path(value)
    except ValueError as error:
        raise ValueError(f"Selected {subject} is not a safe relative path.") from error


def _prepare(
    source: object, source_package: Path, source_root: Path
) -> tuple[dict[str, object], list[tuple[Path, PurePosixPath]]]:
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("routes"), dict)
        or not source["routes"]
    ):
        raise ValueError("Selected package routes have invalid structure.")
    copies: list[tuple[Path, PurePosixPath]] = []
    artifacts: list[dict[str, str]] = []
    routes: dict[str, object] = {}
    seen_paths: set[str] = set()
    seen_routes: set[str] = set()
    for route_name, route in source["routes"].items():
        route_segment = _safe_relative(route_name, "route name")
        if len(route_segment.parts) != 1 or route_name.casefold() in seen_routes:
            raise ValueError("Selected route names must be unique path segments.")
        seen_routes.add(route_name.casefold())
        if not isinstance(route["models"], dict) or not route["models"]:
            raise ValueError("Selected route models have invalid structure.")
        targets: list[dict[str, object]] = []
        for model_name, models in route["models"].items():
            if not isinstance(models, dict) or not models:
                raise ValueError("Selected route models have invalid structure.")
            for name, selected in models.items():
                source_relative = _safe_relative(selected["file"], "artifact path")
                artifact = (source_root / source_relative).resolve(strict=True)
                if not artifact.is_relative_to(source_root) or not artifact.is_file():
                    raise ValueError("Selected artifact escapes the source package.")
                digest = selected["sha256"]
                if (
                    not isinstance(digest, str)
                    or not _HASH.fullmatch(digest)
                    or _sha256(artifact) != digest
                ):
                    raise ValueError("Selected artifact hash differs from source metadata.")
                relative = PurePosixPath("models") / route_segment / artifact.name
                if relative.as_posix().casefold() in seen_paths:
                    raise ValueError("Selected artifacts have colliding destinations.")
                seen_paths.add(relative.as_posix().casefold())
                copies.append((artifact, relative))
                targets.append(
                    {
                        "name": name,
                        "target": selected["target"],
                        "kind": selected["kind"],
                        "features": selected["features"],
                        "artifact_path": relative.as_posix(),
                        "source_metadata": {
                            "model_name": model_name,
                            "alpha": selected["alpha"],
                            "best_rounds": selected["best_rounds"],
                            "provenance": selected["provenance"],
                            "source_file": selected["file"],
                            "source_model_index": selected["source_model_index"],
                            "validation_metrics": selected["validation_metrics"],
                        },
                    }
                )
                artifacts.append({"path": relative.as_posix(), "sha256": digest})
        routes[route_name] = {
            "default_model": route["default"],
            "route_metadata": {
                "models": list(route["models"]),
                "outside_ranges": route["outside_ranges"],
                "overrides": route["overrides"],
                "qualified": route["qualified"],
                "status": route["status"],
            },
            "targets": targets,
        }
    document = {
        "schema_version": "quakestrike.model-release.v1",
        "release_id": str(SEIS_RELEASE_ID),
        "version_label": "SEIS 1.0",
        "input_schema_version": "quakestrike.prediction-input.v1",
        "output_schema_version": "quakestrike.prediction-output.v1",
        "provenance": {
            "package_name": "balanced-selection-anchor-exploratory-01",
            "package_status": source["status"],
            "deployment_authorized": source["deployment_authorized"],
            "path_base": source["path_base"],
            "registry_sha256": source["registry_sha256"],
            "routes_sha256": _sha256(source_package / "routes.json"),
            "source_package": "baselines/attempt-2/stratified-baseline-02/"
            "chosen-models/balanced-selection-anchor-exploratory-01",
            "source_policy": {
                key: source[key]
                for key in (
                    "schema_version",
                    "mode",
                    "primary_weighting",
                    "secondary_policy",
                    "baseline",
                    "band_bounds",
                )
            },
        },
        "postprocessing": source["postprocessing"],
        "routes": routes,
        "artifacts": artifacts,
    }
    return document, copies


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
