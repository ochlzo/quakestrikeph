"""Explicit recovery of the live revisions skipped before catalog coverage existed."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select

from quakestrike.application.features import PredictionSnapshotRequest, decide_prediction_snapshot
from quakestrike.application.reconciliation import coverage_for_anchor, merge_history_coverages
from quakestrike.domain.features import HISTORY_WINDOW, INPUT_SCHEMA_VERSION, HistoryCoverage
from quakestrike.infrastructure.database.engine import SessionFactory
from quakestrike.infrastructure.database.feature_history import (
    SqlAlchemyFeatureHistoryQuery,
    _observation_from_row,
)
from quakestrike.infrastructure.database.prediction import OUTPUT_SCHEMA_VERSION
from quakestrike.infrastructure.database.tables import (
    audit_logs,
    earthquake_event_revisions,
    earthquake_events,
    ingestion_runs,
    job_dispatches,
    model_releases,
    prediction_jobs,
    source_catalog_evidence,
)

SOURCE_RUN_ID = UUID("adc80d19-d105-4ef7-b427-6bc52f133b4d")
AUDIT_ACTION = "historical_prediction_recovered"
SKIP_REASON = "history_coverage_unavailable"


class UnsafeHistoricalRecovery(ValueError):
    """Existing work or source evidence needs operator investigation."""


class SqlAlchemyHistoricalRecovery:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        target_release_id: UUID,
        bootstrap_run_id: UUID,
        bootstrap_sha256: str,
        bootstrap_coverage: HistoryCoverage,
    ) -> None:
        self._session_factory = session_factory
        self._release_id = target_release_id
        self._bootstrap_run_id = bootstrap_run_id
        self._bootstrap_sha256 = bootstrap_sha256
        self._bootstrap_coverage = bootstrap_coverage

    def run(
        self,
        *,
        apply: bool,
        max_new_jobs: int = 50,
        progress: Callable[[dict[str, int]], None] | None = None,
    ) -> dict[str, int]:
        """Commit one revision and its audit at a time; reruns validate prior work."""

        if max_new_jobs < 1:
            raise ValueError("The recovery batch size must be positive.")

        with self._session_factory() as session:
            source = session.execute(
                select(ingestion_runs).where(ingestion_runs.c.run_id == SOURCE_RUN_ID)
            ).one_or_none()
            bootstrap = session.execute(
                select(ingestion_runs).where(ingestion_runs.c.run_id == self._bootstrap_run_id)
            ).one_or_none()
            release = session.execute(
                select(model_releases).where(model_releases.c.model_release_id == self._release_id)
            ).one_or_none()
            if (
                source is None
                or source.status != "succeeded"
                or source.trigger_type not in {"scheduled", "manual"}
                or bootstrap is None
                or bootstrap.status != "succeeded"
                or bootstrap.trigger_type != "backfill"
                or bootstrap.bootstrap_snapshot_sha256 != self._bootstrap_sha256
                or not self._bootstrap_coverage.complete
                or release is None
                or release.input_schema_version != INPUT_SCHEMA_VERSION
                or release.output_schema_version != OUTPUT_SCHEMA_VERSION
            ):
                raise UnsafeHistoricalRecovery("Source, bootstrap, or model evidence is invalid.")
            revisions = earthquake_event_revisions
            ids = session.scalars(
                select(revisions.c.event_revision_id)
                .where(
                    revisions.c.ingestion_run_id == SOURCE_RUN_ID,
                    revisions.c.prediction_skip_reason == SKIP_REASON,
                )
                .order_by(revisions.c.event_time, revisions.c.event_revision_id)
            ).all()
            if not ids:
                raise UnsafeHistoricalRecovery("The source run has no matching skipped revisions.")
            first_time, last_time = session.execute(
                select(func.min(revisions.c.event_time), func.max(revisions.c.event_time)).where(
                    revisions.c.event_revision_id.in_(ids)
                )
            ).one()
            live_coverages = session.execute(
                select(
                    source_catalog_evidence.c.run_id,
                    source_catalog_evidence.c.coverage_start,
                    source_catalog_evidence.c.coverage_end,
                )
                .join(ingestion_runs, ingestion_runs.c.run_id == source_catalog_evidence.c.run_id)
                .where(
                    ingestion_runs.c.status == "succeeded",
                    source_catalog_evidence.c.coverage_end >= first_time - HISTORY_WINDOW,
                    source_catalog_evidence.c.coverage_start <= last_time,
                )
                .order_by(source_catalog_evidence.c.coverage_start)
            ).all()
            merged = merge_history_coverages(
                [self._bootstrap_coverage]
                + [
                    HistoryCoverage(row.coverage_start, row.coverage_end, True)
                    for row in live_coverages
                ]
            )
            coverage_run_ids = [str(row.run_id) for row in live_coverages]

        counts: Counter[str] = Counter(total=len(ids))
        for index, revision_id in enumerate(ids, 1):
            with self._session_factory() as session, session.begin():
                revision = (
                    session.execute(
                        select(earthquake_event_revisions).where(
                            earthquake_event_revisions.c.event_revision_id == revision_id
                        )
                    )
                    .mappings()
                    .one()
                )
                event = session.execute(
                    select(earthquake_events)
                    .where(earthquake_events.c.event_id == revision["event_id"])
                    .with_for_update()
                ).one()
                latest = session.scalar(
                    select(func.max(earthquake_event_revisions.c.revision_number)).where(
                        earthquake_event_revisions.c.event_id == revision["event_id"]
                    )
                )
                if (
                    event.superseded_by_event_id is not None
                    or revision["revision_number"] != latest
                ):
                    counts["superseded"] += 1
                    continue
                coverage = coverage_for_anchor(revision["event_time"], merged)
                anchor = _observation_from_row(revision)
                history = SqlAlchemyFeatureHistoryQuery.select_prior_history_in_session(
                    session, anchor, coverage=coverage, known_at=revision["ingested_at"]
                )
                decision = decide_prediction_snapshot(
                    PredictionSnapshotRequest(
                        anchor=anchor,
                        history=history.observations,
                        coverage=history.coverage,
                        input_schema_version=release.input_schema_version,
                    )
                )
                if decision.snapshot is None:
                    counts[decision.decision.skip_reason or "ineligible"] += 1
                    continue
                snapshot = decision.snapshot
                existing = session.execute(
                    select(prediction_jobs).where(
                        prediction_jobs.c.event_revision_id == revision_id
                    )
                ).one_or_none()
                if existing is not None:
                    dispatch = session.execute(
                        select(job_dispatches).where(
                            job_dispatches.c.prediction_job_id == existing.job_id
                        )
                    ).one_or_none()
                    audit = session.execute(
                        select(audit_logs).where(
                            audit_logs.c.action == AUDIT_ACTION,
                            audit_logs.c.target_type == "event_revision",
                            audit_logs.c.target_id == str(revision_id),
                        )
                    ).one_or_none()
                    if (
                        existing.model_release_id != self._release_id
                        or existing.input_snapshot_hash != snapshot.sha256
                        or existing.input_snapshot_json != dict(snapshot.values)
                        or existing.correlation_id != source.correlation_id
                        or dispatch is None
                        or audit is None
                        or audit._mapping["metadata"]["job_id"] != str(existing.job_id)
                        or audit._mapping["metadata"]["dispatch_id"] != str(dispatch.dispatch_id)
                    ):
                        raise UnsafeHistoricalRecovery(
                            f"Existing work conflicts for {revision_id}."
                        )
                    counts["reused"] += 1
                    continue
                counts["eligible"] += 1
                if apply:
                    if counts["created"] >= max_new_jobs:
                        counts["deferred"] += 1
                        continue
                    now = datetime.now(UTC)
                    job_id, dispatch_id = uuid4(), uuid4()
                    session.execute(
                        insert(prediction_jobs).values(
                            job_id=job_id,
                            event_revision_id=revision_id,
                            model_release_id=self._release_id,
                            input_snapshot_hash=snapshot.sha256,
                            input_snapshot_json=dict(snapshot.values),
                            idempotency_key=(
                                f"prediction:{revision_id}:{self._release_id}:{snapshot.sha256}"
                            ),
                            status="pending",
                            requested_at=now,
                            correlation_id=source.correlation_id,
                        )
                    )
                    session.execute(
                        insert(job_dispatches).values(
                            dispatch_id=dispatch_id,
                            prediction_job_id=job_id,
                            status="pending",
                            next_dispatch_at=now,
                        )
                    )
                    session.execute(
                        insert(audit_logs).values(
                            audit_id=uuid4(),
                            actor_type="system",
                            actor_service="operator-cli",
                            action=AUDIT_ACTION,
                            target_type="event_revision",
                            target_id=str(revision_id),
                            outcome="succeeded",
                            reason_code=SKIP_REASON,
                            correlation_id=source.correlation_id,
                            metadata={
                                "source_run_id": str(SOURCE_RUN_ID),
                                "bootstrap_run_id": str(self._bootstrap_run_id),
                                "bootstrap_snapshot_sha256": self._bootstrap_sha256,
                                "coverage_run_ids": coverage_run_ids,
                                "coverage_start": coverage.start.isoformat(),
                                "coverage_end": coverage.end.isoformat(),
                                "model_release_id": str(self._release_id),
                                "input_snapshot_hash": snapshot.sha256,
                                "job_id": str(job_id),
                                "dispatch_id": str(dispatch_id),
                                "historical_no_alert": True,
                            },
                        )
                    )
                    counts["created"] += 1
            if progress is not None and index % 50 == 0:
                progress(dict(counts))
        result = dict(counts)
        for key in ("superseded", "eligible", "created", "reused", "deferred"):
            result.setdefault(key, 0)
        return result
