"""Read verified PHIVOLCS coverage and simulation inputs from one database view."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from quakestrike.application.reconciliation import merge_history_coverages
from quakestrike.domain.features import (
    HISTORY_WINDOW,
    FeatureObservation,
    HistoryCoverage,
    build_features,
)
from quakestrike.infrastructure.bootstrap import load_run_manifest, load_snapshot_for_manifest
from quakestrike.infrastructure.database.feature_history import SqlAlchemyFeatureHistoryQuery
from quakestrike.infrastructure.database.tables import ingestion_runs, source_catalog_evidence


@dataclass(frozen=True, slots=True)
class CatalogStatus:
    status: Literal["current", "stale", "too_old", "insufficient_history"]
    cutoff: datetime | None

    def public_status(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "catalogCutoff": utc_timestamp(self.cutoff) if self.cutoff else None,
        }


def utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def catalog_status(coverage: Iterable[HistoryCoverage], now: datetime) -> CatalogStatus:
    """Pick the newest end that has seven uninterrupted elapsed days before it."""
    verified = (interval for interval in coverage if interval.end and interval.end <= now)
    for interval in reversed(merge_history_coverages(verified)):
        assert interval.start is not None and interval.end is not None
        cutoff = interval.end.astimezone(UTC)
        if cutoff - interval.start.astimezone(UTC) < HISTORY_WINDOW:
            continue
        age = now - cutoff
        if age > timedelta(weeks=7):
            return CatalogStatus("too_old", cutoff)
        return CatalogStatus("stale" if age > timedelta(days=1) else "current", cutoff)
    return CatalogStatus("insufficient_history", None)


@dataclass(frozen=True, slots=True)
class BootstrapCoverage:
    run_id: UUID
    snapshot_hash: str
    enriched_hash: str | None
    coverage: HistoryCoverage

    @classmethod
    def load(cls, manifest_path: Path) -> "BootstrapCoverage":
        manifest = load_run_manifest(manifest_path)
        snapshot = load_snapshot_for_manifest(manifest)
        if (
            manifest["status"] != "succeeded"
            or snapshot.sha256 != manifest["snapshot_sha256"]
            or not snapshot.coverage.complete
        ):
            raise ValueError("The simulator bootstrap coverage could not be verified.")
        return cls(
            UUID(manifest["run_id"]),
            snapshot.sha256,
            manifest.get("enriched_snapshot_sha256"),
            snapshot.coverage.history_coverage(),
        )


class SimulationCatalog:
    def __init__(self, engine: Engine, bootstrap: BootstrapCoverage | None) -> None:
        self.engine = engine
        self.bootstrap = bootstrap

    def read(
        self, now: datetime, scenario: Mapping[str, float] | None = None
    ) -> tuple[CatalogStatus, Mapping[str, object] | None]:
        with (
            self.engine.connect().execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            ) as connection,
            Session(bind=connection) as session,
            session.begin(),
        ):
            status = catalog_status(self._coverage(session, now), now)
            if scenario is None or status.status not in {"current", "stale"}:
                return status, None
            cutoff = status.cutoff
            assert cutoff is not None
            history = SqlAlchemyFeatureHistoryQuery.select_history_at_in_session(session, cutoff)
            anchor = FeatureObservation(
                event_id=None,
                event_time=cutoff,
                time_precision="second",
                latitude=scenario["latitude"],
                longitude=scenario["longitude"],
                depth_km=scenario["depthKm"],
                magnitude=scenario["magnitude"],
            )
            return status, build_features(anchor, history.observations)

    def _coverage(self, session: Session, now: datetime) -> Iterable[HistoryCoverage]:
        evidence = source_catalog_evidence.c
        runs = ingestion_runs.c
        rows = session.execute(
            select(evidence.coverage_start, func.max(evidence.coverage_end))
            .select_from(
                source_catalog_evidence.join(ingestion_runs, runs.run_id == evidence.run_id)
            )
            .where(runs.status == "succeeded", evidence.coverage_end <= now)
            .group_by(evidence.coverage_start)
        )
        for start, end in rows:
            yield HistoryCoverage(start, end, True)
        if self.bootstrap is not None and session.scalar(
            select(runs.run_id).where(
                runs.run_id == self.bootstrap.run_id,
                runs.status == "succeeded",
                runs.trigger_type == "backfill",
                runs.bootstrap_snapshot_sha256 == self.bootstrap.snapshot_hash,
                runs.bootstrap_enriched_snapshot_sha256 == self.bootstrap.enriched_hash,
            )
        ):
            yield self.bootstrap.coverage
