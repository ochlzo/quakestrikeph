"""Read preserved bootstrap files and publish reconstructed evidence exclusively."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from quakestrike.application.bootstrap_recovery import BootstrapRecoveryCounts
from quakestrike.application.persistence import IngestionRunState
from quakestrike.infrastructure.bootstrap import (
    BootstrapSnapshot,
    BootstrapSnapshotError,
    evaluate_bootstrap_readiness,
    load_bootstrap_snapshot,
    load_enriched_snapshot,
    load_run_manifest,
    new_run_manifest,
)


def publish_exclusively(path: Path, payload: bytes) -> None:
    """Publish a complete file without ever replacing existing evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".bootstrap-recovery-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class FileBootstrapRecoveryEvidence:
    def __init__(self, *, required_available_through: datetime | None):
        self._required_available_through = required_available_through

    def source_path(self, target: Path, sha256: str | None) -> Path | None:
        path = target.parent / "source-snapshots" / f"{sha256}.source.json"
        return path if path.is_file() else None

    def load_source(self, path: Path) -> BootstrapSnapshot:
        return load_bootstrap_snapshot(
            path, required_available_through=self._required_available_through
        )

    def load_enriched(
        self, path: Path, source: BootstrapSnapshot, sha256: str
    ) -> BootstrapSnapshot:
        cache = path.resolve()
        if hashlib.sha256(cache.read_bytes()).hexdigest() != sha256:
            raise BootstrapSnapshotError("The enrichment cache hash does not match.")
        return load_enriched_snapshot(cache, source)

    def new_manifest(self, snapshot: BootstrapSnapshot) -> dict[str, Any]:
        return new_run_manifest(snapshot)

    def load_manifest(self, path: Path) -> dict[str, Any] | None:
        return load_run_manifest(path) if path.exists() else None

    def readiness_error(
        self,
        snapshot: BootstrapSnapshot,
        manifest: Mapping[str, Any],
        state: IngestionRunState,
        counts: BootstrapRecoveryCounts,
    ) -> str | None:
        readiness = evaluate_bootstrap_readiness(
            snapshot,
            manifest,
            state,
            history_observation_count=counts.history_observations,
            usable_history_count=counts.usable_history,
            database_counts=counts.database,
        )
        return None if readiness.ready else readiness.reason

    def publish(self, path: Path, payload: bytes) -> None:
        publish_exclusively(path, payload)
