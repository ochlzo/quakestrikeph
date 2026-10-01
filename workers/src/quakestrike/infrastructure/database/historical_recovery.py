"""PostgreSQL reads and atomic writes for historical prediction recovery."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from quakestrike.application.historical_recovery import (
    AUDIT_ACTION,
    RECOVERABLE_SKIP_REASONS,
    SKIP_REASON,
    SOURCE_RUN_ID,
    ExistingAudit,
    ExistingDispatch,
    ExistingJob,
    LiveCoverageEvidence,
    RecoveryCandidate,
    RecoveryEvidence,
    ReleaseEvidence,
    RunEvidence,
    UnsafeHistoricalRecovery,
)
from quakestrike.domain.features import HISTORY_WINDOW, FeatureSnapshot, HistoryCoverage
from quakestrike.infrastructure.database.engine import SessionFactory
from quakestrike.infrastructure.database.feature_history import (
    SqlAlchemyFeatureHistoryQuery,
    _observation_from_row,
)
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


class SqlAlchemyHistoricalRecovery:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        target_release_id: UUID,
        bootstrap_run_id: UUID,
        source_run_id: UUID = SOURCE_RUN_ID,
        skip_reason: str = SKIP_REASON,
    ) -> None:
        if skip_reason not in RECOVERABLE_SKIP_REASONS:
            raise UnsafeHistoricalRecovery("The selected skip reason is not recoverable.")
        self._source_run_id = source_run_id
        self._skip_reason = skip_reason
        self._session_factory = session_factory
        self._release_id = target_release_id
        self._bootstrap_run_id = bootstrap_run_id

    def evidence(self) -> RecoveryEvidence:
        with self._session_factory() as session:
            source = session.execute(
                select(ingestion_runs).where(ingestion_runs.c.run_id == self._source_run_id)
            ).one_or_none()
            bootstrap = session.execute(
                select(ingestion_runs).where(ingestion_runs.c.run_id == self._bootstrap_run_id)
            ).one_or_none()
            release = session.execute(
                select(model_releases).where(model_releases.c.model_release_id == self._release_id)
            ).one_or_none()
            revisions = earthquake_event_revisions
            ids = tuple(
                session.scalars(
                    select(revisions.c.event_revision_id)
                    .where(
                        revisions.c.ingestion_run_id == self._source_run_id,
                        revisions.c.prediction_skip_reason == self._skip_reason,
                    )
                    .order_by(revisions.c.event_time, revisions.c.event_revision_id)
                ).all()
            )
            coverages: tuple[LiveCoverageEvidence, ...] = ()
            if ids:
                first_time, last_time = session.execute(
                    select(
                        func.min(revisions.c.event_time), func.max(revisions.c.event_time)
                    ).where(revisions.c.event_revision_id.in_(ids))
                ).one()
                rows = session.execute(
                    select(
                        source_catalog_evidence.c.run_id,
                        source_catalog_evidence.c.coverage_start,
                        source_catalog_evidence.c.coverage_end,
                    )
                    .join(
                        ingestion_runs, ingestion_runs.c.run_id == source_catalog_evidence.c.run_id
                    )
                    .where(
                        ingestion_runs.c.status == "succeeded",
                        source_catalog_evidence.c.coverage_end >= first_time - HISTORY_WINDOW,
                        source_catalog_evidence.c.coverage_start <= last_time,
                    )
                    .order_by(source_catalog_evidence.c.coverage_start)
                ).all()
                coverages = tuple(
                    LiveCoverageEvidence(
                        row.run_id, HistoryCoverage(row.coverage_start, row.coverage_end, True)
                    )
                    for row in rows
                )
            return RecoveryEvidence(
                source_run=_run_evidence(source),
                bootstrap_run=_run_evidence(bootstrap),
                release=(
                    ReleaseEvidence(release.input_schema_version, release.output_schema_version)
                    if release is not None
                    else None
                ),
                candidate_ids=ids,
                live_coverages=coverages,
            )

    @contextmanager
    def transaction(self, revision_id: UUID) -> Iterator[SqlAlchemyRecoveryTransaction]:
        with self._session_factory() as session, session.begin():
            yield SqlAlchemyRecoveryTransaction(
                session, revision_id, self._source_run_id, self._skip_reason
            )


def _run_evidence(row) -> RunEvidence | None:
    if row is None:
        return None
    return RunEvidence(
        status=row.status,
        trigger_type=row.trigger_type,
        correlation_id=row.correlation_id,
        snapshot_sha256=row.bootstrap_snapshot_sha256,
    )


class SqlAlchemyRecoveryTransaction:
    def __init__(
        self, session: Session, revision_id: UUID, source_run_id: UUID, skip_reason: str
    ) -> None:
        self._session = session
        self._revision_id = revision_id
        self._source_run_id = source_run_id
        self._skip_reason = skip_reason

    def load(self) -> RecoveryCandidate:
        session = self._session
        revision = (
            session.execute(
                select(earthquake_event_revisions).where(
                    earthquake_event_revisions.c.event_revision_id == self._revision_id,
                    earthquake_event_revisions.c.ingestion_run_id == self._source_run_id,
                    earthquake_event_revisions.c.prediction_skip_reason == self._skip_reason,
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
        anchor = _observation_from_row(revision)
        history = SqlAlchemyFeatureHistoryQuery.select_prior_history_in_session(
            session, anchor, known_at=revision["ingested_at"]
        )
        job = session.execute(
            select(prediction_jobs).where(prediction_jobs.c.event_revision_id == self._revision_id)
        ).one_or_none()
        dispatch = (
            session.execute(
                select(job_dispatches).where(job_dispatches.c.prediction_job_id == job.job_id)
            ).one_or_none()
            if job is not None
            else None
        )
        audit = session.execute(
            select(audit_logs).where(
                audit_logs.c.action == AUDIT_ACTION,
                audit_logs.c.target_type == "event_revision",
                audit_logs.c.target_id == str(self._revision_id),
            )
        ).one_or_none()
        return RecoveryCandidate(
            revision_id=self._revision_id,
            revision_number=revision["revision_number"],
            latest_revision_number=latest,
            event_superseded=event.superseded_by_event_id is not None,
            anchor=anchor,
            history=history.observations,
            job=(
                ExistingJob(
                    job_id=job.job_id,
                    model_release_id=job.model_release_id,
                    input_snapshot_hash=job.input_snapshot_hash,
                    input_snapshot_json=job.input_snapshot_json,
                    idempotency_key=job.idempotency_key,
                    correlation_id=job.correlation_id,
                )
                if job is not None
                else None
            ),
            dispatch=ExistingDispatch(dispatch.dispatch_id) if dispatch is not None else None,
            audit=(
                ExistingAudit(
                    actor_type=audit.actor_type,
                    actor_service=audit.actor_service,
                    outcome=audit.outcome,
                    reason_code=audit.reason_code,
                    correlation_id=audit.correlation_id,
                    metadata=audit._mapping["metadata"],
                )
                if audit is not None
                else None
            ),
        )

    def create_work(
        self,
        *,
        job_id: UUID,
        dispatch_id: UUID,
        release_id: UUID,
        snapshot: FeatureSnapshot,
        correlation_id: UUID,
        audit_metadata: Mapping[str, object],
    ) -> None:
        now = datetime.now(UTC)
        self._session.execute(
            insert(prediction_jobs).values(
                job_id=job_id,
                event_revision_id=self._revision_id,
                model_release_id=release_id,
                input_snapshot_hash=snapshot.sha256,
                input_snapshot_json=dict(snapshot.values),
                idempotency_key=f"prediction:{self._revision_id}:{release_id}:{snapshot.sha256}",
                status="pending",
                requested_at=now,
                correlation_id=correlation_id,
            )
        )
        self._session.execute(
            insert(job_dispatches).values(
                dispatch_id=dispatch_id,
                prediction_job_id=job_id,
                status="pending",
                next_dispatch_at=now,
            )
        )
        self._session.execute(
            insert(audit_logs).values(
                audit_id=uuid4(),
                actor_type="system",
                actor_service="operator-cli",
                action=AUDIT_ACTION,
                target_type="event_revision",
                target_id=str(self._revision_id),
                outcome="succeeded",
                reason_code=self._skip_reason,
                correlation_id=correlation_id,
                metadata=dict(audit_metadata),
            )
        )
