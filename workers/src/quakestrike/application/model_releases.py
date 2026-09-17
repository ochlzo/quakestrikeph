"""Explicit immutable model-release registration contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ModelReleaseRecord:
    model_release_id: UUID
    version_label: str
    artifact_manifest_uri: str
    artifact_manifest_hash: str
    input_schema_version: str
    output_schema_version: str


class ModelReleaseRegistry(Protocol):
    def register(self, release: ModelReleaseRecord) -> bool:
        """Insert a verified release, or return False for an exact replay."""

    def get(self, release_id: UUID) -> ModelReleaseRecord | None:
        """Read a release without changing the registry."""
