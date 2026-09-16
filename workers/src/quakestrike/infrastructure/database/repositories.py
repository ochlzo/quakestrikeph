"""SQLAlchemy implementation of the ingestion transaction contracts."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.orm import Session

from quakestrike.application.persistence import (
    EventTransactionRequest,
    EventTransactionResult,
    IngestionTransactions,
    RunDispatchRequest,
    RunDispatchResult,
)
from quakestrike.infrastructure.database.engine import SessionFactory
from quakestrike.infrastructure.database.tables import (
    earthquake_event_revisions,
    earthquake_events,
    ingestion_runs,
    job_dispatches,
    prediction_jobs,
)

_SCHEDULE_LOCK_KEY = 5_173_835_459
# PostgreSQL keeps two-int advisory locks separate from one-bigint locks. The first
# key reserves an event namespace, so these locks cannot overlap the scheduler lock.
_EVENT_LOCK_NAMESPACE = 1_906_202_609


class SqlAlchemyIngestionTransactions(IngestionTransactions):
    """Keep each logical creation operation inside one database transaction."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def create_run_with_dispatch(self, request: RunDispatchRequest) -> RunDispatchResult:
        with self._session_factory() as session, session.begin():
            session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _SCHEDULE_LOCK_KEY},
            )
            existing = session.execute(
                select(ingestion_runs.c.run_id, job_dispatches.c.dispatch_id)
                .join(
                    job_dispatches,
                    job_dispatches.c.ingestion_run_id == ingestion_runs.c.run_id,
                )
                .where(ingestion_runs.c.status.in_(("pending", "running", "retry_wait")))
                .with_for_update(of=ingestion_runs)
            ).one_or_none()
            if existing is not None:
                return RunDispatchResult(
                    run_id=existing.run_id,
                    dispatch_id=existing.dispatch_id,
                    created=False,
                )

            run_values: dict[str, object] = {
                "run_id": request.run_id,
                "trigger_type": request.trigger_type,
                "correlation_id": request.correlation_id,
            }
            if request.requested_at is not None:
                run_values["requested_at"] = request.requested_at
            session.execute(insert(ingestion_runs).values(**run_values))
            session.execute(
                insert(job_dispatches).values(
                    dispatch_id=request.dispatch_id,
                    ingestion_run_id=request.run_id,
                )
            )
            return RunDispatchResult(
                run_id=request.run_id,
                dispatch_id=request.dispatch_id,
                created=True,
            )

    def process_event(self, request: EventTransactionRequest) -> EventTransactionResult:
        if request.prediction is not None and request.revision is None:
            raise ValueError("Prediction work requires a revision in the same transaction.")
        if (
            request.revision is not None
            and request.revision.ingestion_run_id != request.ingestion_run_id
        ):
            raise ValueError("The revision and event transaction must use the same ingestion run.")

        with self._session_factory() as session, session.begin():
            self._lock_event_identity(session, request.event_id)
            event_exists = self._lock_event(session, request.event_id)
            if event_exists:
                session.execute(
                    update(earthquake_events)
                    .where(earthquake_events.c.event_id == request.event_id)
                    .values(last_seen_run_id=request.ingestion_run_id, updated_at=func.now())
                )
            else:
                session.execute(
                    insert(earthquake_events).values(
                        event_id=request.event_id,
                        first_seen_run_id=request.ingestion_run_id,
                        last_seen_run_id=request.ingestion_run_id,
                    )
                )

            if request.revision is None:
                return EventTransactionResult(
                    event_id=request.event_id,
                    event_revision_id=None,
                    revision_number=None,
                    prediction_job_id=None,
                    dispatch_id=None,
                    event_created=not event_exists,
                    revision_created=False,
                    prediction_created=False,
                )

            revision = request.revision
            existing_revision = self._find_existing_revision(session, request)
            revision_created = existing_revision is None
            if existing_revision is None:
                revision_number = (
                    session.scalar(
                        select(
                            func.coalesce(func.max(earthquake_event_revisions.c.revision_number), 0)
                        ).where(earthquake_event_revisions.c.event_id == request.event_id)
                    )
                    + 1
                )
                session.execute(
                    insert(earthquake_event_revisions).values(
                        event_revision_id=revision.event_revision_id,
                        event_id=request.event_id,
                        revision_number=revision_number,
                        ingestion_run_id=revision.ingestion_run_id,
                        source_bulletin_id=revision.source_bulletin_id,
                        source_event_group_id=revision.source_event_group_id,
                        source_url=revision.source_url,
                        source_time_precision=revision.source_time_precision,
                        event_time=revision.event_time,
                        latitude=revision.latitude,
                        longitude=revision.longitude,
                        depth_km=revision.depth_km,
                        magnitude=revision.magnitude,
                        location_description=revision.location_description,
                        origin=revision.origin,
                    )
                )
                revision_id = revision.event_revision_id
            else:
                revision_id = existing_revision.event_revision_id
                revision_number = existing_revision.revision_number

            if request.prediction is None:
                return EventTransactionResult(
                    event_id=request.event_id,
                    event_revision_id=revision_id,
                    revision_number=revision_number,
                    prediction_job_id=None,
                    dispatch_id=None,
                    event_created=not event_exists,
                    revision_created=revision_created,
                    prediction_created=False,
                )

            prediction = request.prediction
            self._reject_prediction_identity_collisions(session, prediction, revision_id)
            existing_prediction = session.execute(
                select(
                    prediction_jobs.c.job_id,
                    prediction_jobs.c.input_snapshot_json,
                    job_dispatches.c.dispatch_id,
                )
                .join(
                    job_dispatches,
                    job_dispatches.c.prediction_job_id == prediction_jobs.c.job_id,
                )
                .where(
                    prediction_jobs.c.event_revision_id == revision_id,
                    prediction_jobs.c.model_release_id == prediction.model_release_id,
                    prediction_jobs.c.input_snapshot_hash == prediction.input_snapshot_hash,
                )
            ).one_or_none()
            if existing_prediction is not None:
                if existing_prediction.input_snapshot_json != dict(prediction.input_snapshot_json):
                    raise ValueError("The snapshot hash already identifies different content.")
                return EventTransactionResult(
                    event_id=request.event_id,
                    event_revision_id=revision_id,
                    revision_number=revision_number,
                    prediction_job_id=existing_prediction.job_id,
                    dispatch_id=existing_prediction.dispatch_id,
                    event_created=not event_exists,
                    revision_created=revision_created,
                    prediction_created=False,
                )

            session.execute(
                insert(prediction_jobs).values(
                    job_id=prediction.job_id,
                    event_revision_id=revision_id,
                    model_release_id=prediction.model_release_id,
                    input_snapshot_hash=prediction.input_snapshot_hash,
                    input_snapshot_json=dict(prediction.input_snapshot_json),
                    idempotency_key=prediction.idempotency_key,
                    correlation_id=prediction.correlation_id,
                )
            )
            session.execute(
                insert(job_dispatches).values(
                    dispatch_id=prediction.dispatch_id,
                    prediction_job_id=prediction.job_id,
                )
            )
            return EventTransactionResult(
                event_id=request.event_id,
                event_revision_id=revision_id,
                revision_number=revision_number,
                prediction_job_id=prediction.job_id,
                dispatch_id=prediction.dispatch_id,
                event_created=not event_exists,
                revision_created=revision_created,
                prediction_created=True,
            )

    @staticmethod
    def _lock_event_identity(session: Session, event_id: UUID) -> None:
        lock_key = int.from_bytes(event_id.bytes[:4], byteorder="big", signed=True)
        session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :lock_key)"),
            {"namespace": _EVENT_LOCK_NAMESPACE, "lock_key": lock_key},
        )

    @classmethod
    def _find_existing_revision(cls, session: Session, request: EventTransactionRequest):
        revision = request.revision
        assert revision is not None
        by_id = session.execute(
            select(earthquake_event_revisions).where(
                earthquake_event_revisions.c.event_revision_id == revision.event_revision_id
            )
        ).one_or_none()
        if by_id is not None:
            cls._validate_revision_match(by_id, request)
            return by_id
        if revision.source_bulletin_id is None:
            same_run_revision = session.execute(
                select(earthquake_event_revisions)
                .where(
                    earthquake_event_revisions.c.event_id == request.event_id,
                    earthquake_event_revisions.c.ingestion_run_id == request.ingestion_run_id,
                    earthquake_event_revisions.c.source_bulletin_id.is_(None),
                    earthquake_event_revisions.c.source_event_group_id
                    == revision.source_event_group_id,
                )
                .order_by(earthquake_event_revisions.c.revision_number.desc())
                .limit(1)
            ).one_or_none()
            if same_run_revision is not None and cls._revision_content_matches(
                same_run_revision, request
            ):
                return same_run_revision
            latest_for_event = session.execute(
                select(earthquake_event_revisions)
                .where(earthquake_event_revisions.c.event_id == request.event_id)
                .order_by(earthquake_event_revisions.c.revision_number.desc())
                .limit(1)
            ).one_or_none()
            if (
                latest_for_event is not None
                and latest_for_event.source_bulletin_id is None
                and latest_for_event.source_event_group_id == revision.source_event_group_id
                and cls._revision_content_matches(latest_for_event, request)
            ):
                return latest_for_event
            return None
        by_bulletin = session.execute(
            select(earthquake_event_revisions).where(
                earthquake_event_revisions.c.source_bulletin_id == revision.source_bulletin_id
            )
        ).one_or_none()
        if by_bulletin is not None:
            cls._validate_revision_match(by_bulletin, request)
        return by_bulletin

    @staticmethod
    def _validate_revision_match(existing, request: EventTransactionRequest) -> None:
        if not SqlAlchemyIngestionTransactions._revision_content_matches(existing, request):
            raise ValueError("The revision identity already refers to different content.")

    @staticmethod
    def _revision_content_matches(existing, request: EventTransactionRequest) -> bool:
        revision = request.revision
        assert revision is not None
        expected = {
            "event_id": request.event_id,
            "source_bulletin_id": revision.source_bulletin_id,
            "source_event_group_id": revision.source_event_group_id,
            "source_url": revision.source_url,
            "source_time_precision": revision.source_time_precision,
            "event_time": revision.event_time,
            "latitude": revision.latitude,
            "longitude": revision.longitude,
            "depth_km": revision.depth_km,
            "magnitude": revision.magnitude,
            "location_description": revision.location_description,
            "origin": revision.origin,
        }
        return all(getattr(existing, name) == value for name, value in expected.items())

    @staticmethod
    def _reject_prediction_identity_collisions(
        session: Session, prediction, event_revision_id: UUID
    ) -> None:
        existing_job = session.execute(
            select(prediction_jobs).where(prediction_jobs.c.job_id == prediction.job_id)
        ).one_or_none()
        if existing_job is not None and (
            existing_job.event_revision_id != event_revision_id
            or existing_job.model_release_id != prediction.model_release_id
            or existing_job.input_snapshot_hash != prediction.input_snapshot_hash
            or existing_job.input_snapshot_json != dict(prediction.input_snapshot_json)
        ):
            raise ValueError("The prediction job ID already refers to different work.")
        existing_dispatch = session.execute(
            select(job_dispatches).where(job_dispatches.c.dispatch_id == prediction.dispatch_id)
        ).one_or_none()
        if existing_dispatch is not None and (
            existing_job is None or existing_dispatch.prediction_job_id != existing_job.job_id
        ):
            raise ValueError("The dispatch ID already refers to different work.")

    @staticmethod
    def _lock_event(session: Session, event_id: object) -> bool:
        return (
            session.execute(
                select(earthquake_events.c.event_id)
                .where(earthquake_events.c.event_id == event_id)
                .with_for_update()
            ).scalar_one_or_none()
            is not None
        )
