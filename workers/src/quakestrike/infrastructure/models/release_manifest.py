"""Parse and verify immutable model-release runtime bundles."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from uuid import UUID

from quakestrike.application.model_releases import ModelReleaseRecord
from quakestrike.infrastructure.models.relative_path import safe_relative_path

_SCHEMA_VERSION = "quakestrike.model-release.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
SELECTED_RELEASE_MANIFEST_URI = "seis-1.0/manifest.json"
TRACKED_RELEASE_MANIFEST = (
    Path(__file__).resolve().parents[4] / "model-release-manifests" / SELECTED_RELEASE_MANIFEST_URI
)


class ManifestValidationError(ValueError):
    """Raised when a runtime bundle cannot prove its declared identity."""


@dataclass(frozen=True, slots=True)
class VerifiedReleaseManifest:
    """Validated release data safe to use for registration and startup."""

    release_id: UUID
    version_label: str
    input_schema_version: str
    output_schema_version: str
    manifest_uri: str
    manifest_hash: str
    artifact_paths: tuple[str, ...]
    artifact_hashes: dict[str, str] = dataclass_field(default_factory=dict)


def model_release_record(manifest: VerifiedReleaseManifest) -> ModelReleaseRecord:
    """Convert verified infrastructure data to the inward registration contract."""

    return ModelReleaseRecord(
        model_release_id=manifest.release_id,
        version_label=manifest.version_label,
        artifact_manifest_uri=manifest.manifest_uri,
        artifact_manifest_hash=manifest.manifest_hash,
        input_schema_version=manifest.input_schema_version,
        output_schema_version=manifest.output_schema_version,
    )


def load_verified_release_manifest(
    artifact_directory: Path, manifest_uri: str, *, require_selected_policy: bool = False
) -> VerifiedReleaseManifest:
    """Load a bundle below ``artifact_directory`` and verify every artifact."""

    root = artifact_directory.resolve(strict=True)
    manifest_path = _resolve_within(root, manifest_uri, "manifest URI")
    if manifest_path.name != "manifest.json":
        raise ManifestValidationError("The manifest URI must name manifest.json.")
    try:
        raw_bytes = manifest_path.read_bytes()
        document = json.loads(raw_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestValidationError("The release manifest is not valid JSON.") from error
    _require_canonical_json(raw_bytes, document)
    if require_selected_policy:
        _require_selected_policy(raw_bytes)
    if not isinstance(document, dict):
        raise ManifestValidationError("The release manifest must be an object.")
    _require_exact_keys(
        document,
        {
            "schema_version",
            "release_id",
            "version_label",
            "input_schema_version",
            "output_schema_version",
            "provenance",
            "postprocessing",
            "routes",
            "artifacts",
        },
        "release manifest",
    )
    if document["schema_version"] != _SCHEMA_VERSION:
        raise ManifestValidationError("The release manifest schema version is unsupported.")
    release_id = _as_uuid(document["release_id"])
    version_label = _nonblank_string(document["version_label"], "version label")
    input_schema_version = _nonblank_string(
        document["input_schema_version"], "input schema version"
    )
    output_schema_version = _nonblank_string(
        document["output_schema_version"], "output schema version"
    )
    _validate_provenance(document["provenance"])
    if not isinstance(document["postprocessing"], dict):
        raise ManifestValidationError("The postprocessing metadata must be an object.")
    artifact_paths, artifact_hashes = _validate_routes_and_artifacts(
        manifest_path.parent, document["routes"], document["artifacts"]
    )
    return VerifiedReleaseManifest(
        release_id=release_id,
        version_label=version_label,
        input_schema_version=input_schema_version,
        output_schema_version=output_schema_version,
        manifest_uri=manifest_uri,
        manifest_hash=hashlib.sha256(raw_bytes).hexdigest(),
        artifact_paths=artifact_paths,
        artifact_hashes=artifact_hashes,
    )


def canonical_json_bytes(document: object) -> bytes:
    """Encode a manifest using the single byte representation Phase 3 permits."""

    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _require_canonical_json(raw_bytes: bytes, document: object) -> None:
    if raw_bytes != canonical_json_bytes(document):
        raise ManifestValidationError("The release manifest is not canonical JSON.")


def _require_selected_policy(raw_bytes: bytes) -> None:
    if not TRACKED_RELEASE_MANIFEST.is_file() or raw_bytes != TRACKED_RELEASE_MANIFEST.read_bytes():
        raise ManifestValidationError(
            "The release manifest differs from the approved release policy."
        )


def _resolve_within(root: Path, relative_path: str, subject: str) -> Path:
    try:
        candidate = safe_relative_path(relative_path)
    except ValueError as error:
        raise ManifestValidationError(f"The {subject} must be a safe relative path.") from error
    try:
        resolved = (root / candidate).resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise ManifestValidationError(f"The {subject} escapes the artifact directory.") from error
    return resolved


def _require_exact_keys(value: dict[str, object], expected: set[str], subject: str) -> None:
    if set(value) != expected:
        raise ManifestValidationError(f"The {subject} has missing or unknown fields.")


def _as_uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise ManifestValidationError("The release ID must be a UUID.")
    try:
        return UUID(value)
    except ValueError as error:
        raise ManifestValidationError("The release ID must be a UUID.") from error


def _nonblank_string(value: object, subject: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ManifestValidationError(f"The {subject} must be a nonblank trimmed string.")
    return value


def _validate_provenance(value: object) -> None:
    if not isinstance(value, dict):
        raise ManifestValidationError("The provenance metadata must be an object.")
    _require_exact_keys(
        value,
        {
            "package_name",
            "package_status",
            "deployment_authorized",
            "path_base",
            "registry_sha256",
            "routes_sha256",
            "source_package",
            "source_policy",
        },
        "provenance metadata",
    )
    _nonblank_string(value["package_name"], "package name")
    _nonblank_string(value["package_status"], "package status")
    if not isinstance(value["deployment_authorized"], bool):
        raise ManifestValidationError("The deployment authorization flag must be boolean.")
    for field in ("path_base", "source_package"):
        _nonblank_string(value[field], field.replace("_", " "))
    for field in ("registry_sha256", "routes_sha256"):
        if not isinstance(value[field], str) or not _SHA256.fullmatch(value[field]):
            raise ManifestValidationError(f"The {field} must be lowercase SHA-256.")
    policy = value["source_policy"]
    if not isinstance(policy, dict):
        raise ManifestValidationError("Source policy must be an object.")
    _require_exact_keys(
        policy,
        {
            "schema_version",
            "mode",
            "primary_weighting",
            "secondary_policy",
            "baseline",
            "band_bounds",
        },
        "source policy",
    )
    if not isinstance(policy["schema_version"], int) or isinstance(policy["schema_version"], bool):
        raise ManifestValidationError("Source schema version must be an integer.")
    for field in ("mode", "primary_weighting", "secondary_policy", "baseline", "band_bounds"):
        _nonblank_string(policy[field], field.replace("_", " "))


def _validate_routes_and_artifacts(
    root: Path, routes: object, artifacts: object
) -> tuple[tuple[str, ...], dict[str, str]]:
    if not isinstance(routes, dict) or not routes:
        raise ManifestValidationError("The routes must be a nonempty object.")
    if not isinstance(artifacts, list) or not artifacts:
        raise ManifestValidationError("The artifacts must be a nonempty list.")
    artifact_hashes: dict[str, str] = {}
    normalized_paths: set[str] = set()
    for entry in artifacts:
        if not isinstance(entry, dict):
            raise ManifestValidationError("Each artifact must be an object.")
        _require_exact_keys(entry, {"path", "sha256"}, "artifact")
        path = _nonblank_string(entry["path"], "artifact path")
        normalized = path.casefold()
        if normalized in normalized_paths:
            raise ManifestValidationError("Artifact paths must not duplicate or case-collide.")
        normalized_paths.add(normalized)
        digest = _nonblank_string(entry["sha256"], "artifact hash")
        if not _SHA256.fullmatch(digest):
            raise ManifestValidationError("Each artifact hash must be lowercase SHA-256.")
        actual = hashlib.sha256(
            _resolve_within(root, path, "artifact path").read_bytes()
        ).hexdigest()
        if actual != digest:
            raise ManifestValidationError("An artifact hash does not match its manifest entry.")
        artifact_hashes[path] = digest
    declared_by_route: set[str] = set()
    normalized_routes: set[str] = set()
    for route_name, route in routes.items():
        if not isinstance(route_name, str) or not isinstance(route, dict):
            raise ManifestValidationError("Each route must be an object.")
        try:
            route_segment = safe_relative_path(route_name)
        except ValueError as error:
            raise ManifestValidationError(
                "Route names must be unique safe path segments."
            ) from error
        if len(route_segment.parts) != 1 or route_name.casefold() in normalized_routes:
            raise ManifestValidationError("Route names must be unique safe path segments.")
        normalized_routes.add(route_name.casefold())
        _require_exact_keys(route, {"default_model", "route_metadata", "targets"}, "route")
        _nonblank_string(route["default_model"], "default model")
        if not isinstance(route["route_metadata"], dict):
            raise ManifestValidationError("Route metadata must be an object.")
        _require_exact_keys(
            route["route_metadata"],
            {"models", "outside_ranges", "overrides", "qualified", "status"},
            "route metadata",
        )
        metadata = route["route_metadata"]
        if (
            not isinstance(metadata["models"], list)
            or not metadata["models"]
            or not all(
                isinstance(model, str) and model.strip() == model and model
                for model in metadata["models"]
            )
            or len({model.casefold() for model in metadata["models"]}) != len(metadata["models"])
            or route["default_model"] not in metadata["models"]
            or not isinstance(metadata["outside_ranges"], str)
            or not isinstance(metadata["overrides"], list)
            or not isinstance(metadata["qualified"], bool)
        ):
            raise ManifestValidationError("Route metadata is invalid.")
        _nonblank_string(metadata["status"], "route status")
        targets = route["targets"]
        if not isinstance(targets, list) or not targets:
            raise ManifestValidationError("Each route must declare targets.")
        names: set[str] = set()
        for target in targets:
            if not isinstance(target, dict):
                raise ManifestValidationError("Each route target must be an object.")
            _require_exact_keys(
                target,
                {"name", "target", "kind", "features", "artifact_path", "source_metadata"},
                "route target",
            )
            name = _nonblank_string(target["name"], "route target name")
            if name.casefold() in names:
                raise ManifestValidationError("Route target names must be unique.")
            names.add(name.casefold())
            _nonblank_string(target["target"], "route target")
            _nonblank_string(target["kind"], "route target kind")
            if not isinstance(target["features"], list) or not target["features"]:
                raise ManifestValidationError("Route target features must be a nonempty list.")
            if not all(
                isinstance(feature, str) and feature and feature.strip() == feature
                for feature in target["features"]
            ) or len({feature.casefold() for feature in target["features"]}) != len(
                target["features"]
            ):
                raise ManifestValidationError(
                    "Route target features must be unique trimmed strings."
                )
            if not isinstance(target["source_metadata"], dict):
                raise ManifestValidationError("Route target source metadata must be an object.")
            _require_exact_keys(
                target["source_metadata"],
                {
                    "model_name",
                    "alpha",
                    "best_rounds",
                    "provenance",
                    "source_file",
                    "source_model_index",
                    "validation_metrics",
                },
                "source metadata",
            )
            source_metadata = target["source_metadata"]
            _nonblank_string(source_metadata["model_name"], "model name")
            _nonblank_string(source_metadata["source_file"], "source file")
            _nonblank_string(source_metadata["validation_metrics"], "validation metrics")
            if (
                source_metadata["model_name"] not in metadata["models"]
                or not isinstance(source_metadata["best_rounds"], int)
                or isinstance(source_metadata["best_rounds"], bool)
                or not isinstance(source_metadata["provenance"], dict)
            ):
                raise ManifestValidationError("Source metadata is invalid.")
            _nonblank_string(source_metadata["source_model_index"], "source model index")
            artifact_path = _nonblank_string(target["artifact_path"], "route artifact path")
            if artifact_path not in artifact_hashes:
                raise ManifestValidationError("Every route artifact must be declared exactly once.")
            if artifact_path in declared_by_route:
                raise ManifestValidationError(
                    "An artifact cannot be reused by multiple route targets."
                )
            declared_by_route.add(artifact_path)
    if declared_by_route != set(artifact_hashes):
        raise ManifestValidationError("Every declared artifact must be used by one route target.")
    return tuple(artifact_hashes), artifact_hashes
