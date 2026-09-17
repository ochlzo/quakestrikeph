"""SQLAlchemy implementation of the ingestion transaction contracts."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.orm import Session

from quakestrike.application.features import (
    PredictionSnapshotRequest,
    decide_prediction_snapshot,
)
from quakestrike.application.model_releases import ModelReleaseVerifier
from quakestrike.application.persistence import (
    EventTransactionRequest,
    EventTransactionResult,
    FeatureEventTransactionRequest,
    IngestionTransactions,
    PredictionWorkRequest,
    RunDispatchRequest,
    RunDispatchResult,
)
from quakestrike.domain.features import (
    INPUT_SCHEMA_VERSION,
    PredictionSkipReason,
    build_prediction_decision,
    create_feature_snapshot,
)
from quakestrike.infrastructure.database.engine import SessionFactory
from quakestrike.infrastructure.database.feature_history import (
    SqlAlchemyFeatureHistoryQuery,
    observation_from_revision_request,
)
from quakestrike.infrastructure.database.tables import (
    earthquake_event_revisions,
    earthquake_events,
    ingestion_runs,
    job_dispatches,
    model_releases,
    prediction_jobs,
)

_SCHEDULE_LOCK_KEY = 5_173_835_459
# PostgreSQL keeps two-int advisory locks separate from one-bigint locks. The first
# key reserves an event namespace, so these locks cannot overlap the scheduler lock.
_EVENT_LOCK_NAMESPACE = 1_906_202_609


class SqlAlchemyIngestionTransactions(IngestionTransactions):
    """Keep each logical creation operation inside one database transaction."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        model_release_verifier: ModelReleaseVerifier,
    ) -> None:
        self._session_factory = session_factory
        self._model_release_verifier = model_release_verifier

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
        if request.prediction is not None and not self._is_model_release_verified(
            request.prediction.model_release_id
        ):
            assert request.revision is not None
            request = replace(
                request,
                revision=replace(
                    request.revision,
                    prediction_skip_reason=PredictionSkipReason.MODEL_RELEASE_UNAVAILABLE.value,
                ),
                prediction=None,
            )

        with self._session_factory() as session, session.begin():
            return self._process_event_in_session(session, request)

    def process_event_with_features(
        self, request: FeatureEventTransactionRequest
    ) -> EventTransactionResult:
        """Build prediction input inside the event transaction before committing it."""

        if request.revision.ingestion_run_id != request.ingestion_run_id:
            raise ValueError("The revision and event transaction must use the same ingestion run.")

        model_release_verified = self._is_model_release_verified(request.model_release_id)

        with self._session_factory() as session, session.begin():
            event_created = self._lock_or_create_event(
                session,
                request.event_id,
                request.ingestion_run_id,
            )
            base_request = EventTransactionRequest(
                event_id=request.event_id,
                ingestion_run_id=request.ingestion_run_id,
                revision=request.revision,
            )
            existing_revision = self._find_existing_revision(session, base_request)
            if existing_revision is not None:
                if not model_release_verified:
                    return EventTransactionResult(
                        event_id=request.event_id,
                        event_revision_id=existing_revision.event_revision_id,
                        revision_number=existing_revision.revision_number,
                        prediction_job_id=None,
                        dispatch_id=None,
                        event_created=event_created,
                        revision_created=False,
                        prediction_created=False,
                        prediction_skip_reason=PredictionSkipReason.MODEL_RELEASE_UNAVAILABLE.value,
                    )
                existing_prediction = self._find_latest_prediction(
                    session,
                    existing_revision.event_revision_id,
                    request.model_release_id,
                )
                if existing_prediction is not None:
                    return EventTransactionResult(
                        event_id=request.event_id,
                        event_revision_id=existing_revision.event_revision_id,
                        revision_number=existing_revision.revision_number,
                        prediction_job_id=existing_prediction.job_id,
                        dispatch_id=existing_prediction.dispatch_id,
                        event_created=event_created,
                        revision_created=False,
                        prediction_created=False,
                        prediction_skip_reason=None,
                    )
                return EventTransactionResult(
                    event_id=request.event_id,
                    event_revision_id=existing_revision.event_revision_id,
                    revision_number=existing_revision.revision_number,
                    prediction_job_id=None,
                    dispatch_id=None,
                    event_created=event_created,
                    revision_created=False,
                    prediction_created=False,
                    prediction_skip_reason=existing_revision.prediction_skip_reason,
                )

            anchor = observation_from_revision_request(request.event_id, request.revision)
            gate = build_prediction_decision(
                anchor,
                (),
                request.history_coverage,
                input_schema_version=INPUT_SCHEMA_VERSION,
            )
            snapshot = None
            skip_reason = gate.skip_reason
            if skip_reason is None:
                if not model_release_verified:
                    skip_reason = PredictionSkipReason.MODEL_RELEASE_UNAVAILABLE.value
                else:
                    schema_version = session.scalar(
                        select(model_releases.c.input_schema_version).where(
                            model_releases.c.model_release_id == request.model_release_id
                        )
                    )
                    if schema_version != INPUT_SCHEMA_VERSION:
                        skip_reason = PredictionSkipReason.MODEL_RELEASE_UNAVAILABLE.value
                    else:
                        selection = SqlAlchemyFeatureHistoryQuery.select_prior_history_in_session(
                            session,
                            anchor,
                            coverage=request.history_coverage,
                        )
                        decided = decide_prediction_snapshot(
                            PredictionSnapshotRequest(
                                anchor=anchor,
                                history=selection.observations,
                                coverage=selection.coverage,
                                input_schema_version=schema_version,
                            )
                        )
                        snapshot = decided.snapshot
                        skip_reason = decided.decision.skip_reason

            revision = replace(request.revision, prediction_skip_reason=skip_reason)
            revision_number = self._next_revision_number(session, request.event_id)
            self._insert_revision(
                session,
                request.event_id,
                revision,
                revision_number,
            )
            revision_id = revision.event_revision_id
            if snapshot is None:
                return EventTransactionResult(
                    event_id=request.event_id,
                    event_revision_id=revision_id,
                    revision_number=revision_number,
                    prediction_job_id=None,
                    dispatch_id=None,
                    event_created=event_created,
                    revision_created=True,
                    prediction_created=False,
                    prediction_skip_reason=skip_reason,
                )

            prediction = PredictionWorkRequest(
                job_id=request.job_id or uuid4(),
                dispatch_id=request.dispatch_id or uuid4(),
                model_release_id=request.model_release_id,
                input_snapshot_hash=snapshot.sha256,
                input_snapshot_json=snapshot.values,
                idempotency_key=(
                    request.idempotency_key
                    or f"prediction:{revision_id}:{request.model_release_id}:{snapshot.sha256}"
                ),
                correlation_id=request.correlation_id,
            )
            self._insert_prediction_work(session, prediction, revision_id)
            return EventTransactionResult(
                event_id=request.event_id,
                event_revision_id=revision_id,
                revision_number=revision_number,
                prediction_job_id=prediction.job_id,
                dispatch_id=prediction.dispatch_id,
                event_created=event_created,
                revision_created=True,
                prediction_created=True,
                prediction_skip_reason=None,
            )

    def _process_event_in_session(
        self,
        session: Session,
        request: EventTransactionRequest,
    ) -> EventTransactionResult:
        event_created = self._lock_or_create_event(
            session,
            request.event_id,
            request.ingestion_run_id,
            revision_required=request.revision is not None,
        )
        if request.revision is None:
            return EventTransactionResult(
                event_id=request.event_id,
                event_revision_id=None,
                revision_number=None,
                prediction_job_id=None,
                dispatch_id=None,
                event_created=event_created,
                revision_created=False,
                prediction_created=False,
                prediction_skip_reason=None,
            )

        revision = request.revision
        if request.prediction is not None and revision.prediction_skip_reason is not None:
            raise ValueError("A skipped revision cannot create prediction work.")
        if request.prediction is not None:
            anchor = observation_from_revision_request(request.event_id, revision)
            if (
                build_prediction_decision(anchor, (), None).skip_reason
                == PredictionSkipReason.BELOW_M1.value
            ):
                raise ValueError("Prediction work requires an M1+ revision.")
        existing_revision = self._find_existing_revision(session, request)
        revision_created = existing_revision is None
        if existing_revision is None:
            revision_number = self._next_revision_number(session, request.event_id)
            self._insert_revision(session, request.event_id, revision, revision_number)
            revision_id = revision.event_revision_id
            skip_reason = revision.prediction_skip_reason
        else:
            revision_id = existing_revision.event_revision_id
            revision_number = existing_revision.revision_number
            skip_reason = existing_revision.prediction_skip_reason

        if request.prediction is None:
            return EventTransactionResult(
                event_id=request.event_id,
                event_revision_id=revision_id,
                revision_number=revision_number,
                prediction_job_id=None,
                dispatch_id=None,
                event_created=event_created,
                revision_created=revision_created,
                prediction_created=False,
                prediction_skip_reason=skip_reason,
            )

        prediction, snapshot = self._validated_prediction(session, request.prediction)
        existing_prediction = self._find_prediction(
            session,
            revision_id,
            prediction.model_release_id,
            prediction.input_snapshot_hash,
            snapshot.values,
        )
        if existing_prediction is not None:
            return EventTransactionResult(
                event_id=request.event_id,
                event_revision_id=revision_id,
                revision_number=revision_number,
                prediction_job_id=existing_prediction.job_id,
                dispatch_id=existing_prediction.dispatch_id,
                event_created=event_created,
                revision_created=revision_created,
                prediction_created=False,
                prediction_skip_reason=skip_reason,
            )
        if not revision_created:
            raise ValueError("A replay cannot add prediction work to an existing revision.")

        self._insert_prediction_work(session, prediction, revision_id, snapshot=snapshot)
        return EventTransactionResult(
            event_id=request.event_id,
            event_revision_id=revision_id,
            revision_number=revision_number,
            prediction_job_id=prediction.job_id,
            dispatch_id=prediction.dispatch_id,
            event_created=event_created,
            revision_created=True,
            prediction_created=True,
            prediction_skip_reason=skip_reason,
        )

    @classmethod
    def _lock_or_create_event(
        cls,
        session: Session,
        event_id: UUID,
        ingestion_run_id: UUID,
        *,
        revision_required: bool = True,
    ) -> bool:
        cls._lock_event_identity(session, event_id)
        event_exists = cls._lock_event(session, event_id)
        if event_exists:
            session.execute(
                update(earthquake_events)
                .where(earthquake_events.c.event_id == event_id)
                .values(last_seen_run_id=ingestion_run_id, updated_at=func.now())
            )
            return False
        if not revision_required:
            raise ValueError("A revision-less event transaction requires an existing event.")
        session.execute(
            insert(earthquake_events).values(
                event_id=event_id,
                first_seen_run_id=ingestion_run_id,
                last_seen_run_id=ingestion_run_id,
            )
        )
        return True

    @staticmethod
    def _next_revision_number(session: Session, event_id: UUID) -> int:
        return (
            session.scalar(
                select(
                    func.coalesce(func.max(earthquake_event_revisions.c.revision_number), 0)
                ).where(earthquake_event_revisions.c.event_id == event_id)
            )
            + 1
        )

    @staticmethod
    def _insert_revision(
        session: Session,
        event_id: UUID,
        revision,
        revision_number: int,
    ) -> None:
        session.execute(
            insert(earthquake_event_revisions).values(
                event_revision_id=revision.event_revision_id,
                event_id=event_id,
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
                prediction_skip_reason=revision.prediction_skip_reason,
            )
        )

    @classmethod
    def _validated_prediction(cls, session: Session, prediction: PredictionWorkRequest):
        schema_version = (
            session.scalar(
                select(model_releases.c.input_schema_version).where(
                    model_releases.c.model_release_id == prediction.model_release_id
                )
            )
            or INPUT_SCHEMA_VERSION
        )
        if schema_version != INPUT_SCHEMA_VERSION:
            raise ValueError(
                "The prediction snapshot schema does not match the live feature contract."
            )
        snapshot = create_feature_snapshot(
            prediction.input_snapshot_json,
            input_schema_version=schema_version,
        )
        if snapshot.sha256 != prediction.input_snapshot_hash:
            raise ValueError("The prediction snapshot hash does not match its content.")
        normalized = replace(
            prediction,
            input_snapshot_hash=snapshot.sha256,
            input_snapshot_json=snapshot.values,
        )
        return normalized, snapshot

    @classmethod
    def _insert_prediction_work(
        cls,
        session: Session,
        prediction: PredictionWorkRequest,
        event_revision_id: UUID,
        *,
        snapshot=None,
    ) -> None:
        if snapshot is None:
            prediction, snapshot = cls._validated_prediction(session, prediction)
        cls._reject_prediction_identity_collisions(
            session,
            prediction,
            event_revision_id,
            snapshot.values,
        )
        session.execute(
            insert(prediction_jobs).values(
                job_id=prediction.job_id,
                event_revision_id=event_revision_id,
                model_release_id=prediction.model_release_id,
                input_snapshot_hash=snapshot.sha256,
                input_snapshot_json=dict(snapshot.values),
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

    @staticmethod
    def _find_prediction(
        session: Session,
        event_revision_id: UUID,
        model_release_id: UUID,
        input_snapshot_hash: str,
        input_snapshot_json,
    ):
        row = session.execute(
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
                prediction_jobs.c.event_revision_id == event_revision_id,
                prediction_jobs.c.model_release_id == model_release_id,
                prediction_jobs.c.input_snapshot_hash == input_snapshot_hash,
            )
        ).one_or_none()
        if row is not None and row.input_snapshot_json != dict(input_snapshot_json):
            raise ValueError("The snapshot hash already identifies different content.")
        return row

    @staticmethod
    def _find_latest_prediction(session: Session, event_revision_id: UUID, model_release_id: UUID):
        return session.execute(
            select(prediction_jobs.c.job_id, job_dispatches.c.dispatch_id)
            .join(
                job_dispatches,
                job_dispatches.c.prediction_job_id == prediction_jobs.c.job_id,
            )
            .where(
                prediction_jobs.c.event_revision_id == event_revision_id,
                prediction_jobs.c.model_release_id == model_release_id,
            )
            .order_by(prediction_jobs.c.requested_at.desc())
            .limit(1)
        ).one_or_none()

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
        session: Session,
        prediction: PredictionWorkRequest,
        event_revision_id: UUID,
        input_snapshot_json,
    ) -> None:
        existing_job = session.execute(
            select(prediction_jobs).where(prediction_jobs.c.job_id == prediction.job_id)
        ).one_or_none()
        if existing_job is not None and (
            existing_job.event_revision_id != event_revision_id
            or existing_job.model_release_id != prediction.model_release_id
            or existing_job.input_snapshot_hash != prediction.input_snapshot_hash
            or existing_job.input_snapshot_json != dict(input_snapshot_json)
        ):
            raise ValueError("The prediction job ID already refers to different work.")
        existing_idempotency = session.execute(
            select(prediction_jobs.c.job_id).where(
                prediction_jobs.c.idempotency_key == prediction.idempotency_key
            )
        ).scalar_one_or_none()
        if existing_idempotency is not None and existing_idempotency != prediction.job_id:
            raise ValueError("The prediction idempotency key already refers to different work.")
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

    def _is_model_release_verified(self, release_id: UUID) -> bool:
        try:
            return self._model_release_verifier.is_verified(release_id)
        except Exception:
            return False
