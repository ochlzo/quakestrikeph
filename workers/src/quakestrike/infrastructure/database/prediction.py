"""Fenced prediction claims and atomic forecast completion."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update

from quakestrike.domain.features import INPUT_SCHEMA_VERSION, create_feature_snapshot
from quakestrike.domain.prediction import ForecastOutput
from quakestrike.infrastructure.database.engine import SessionFactory
from quakestrike.infrastructure.database.tables import (
    audit_logs,
    earthquake_event_revisions,
    forecasts,
    job_dispatches,
    model_releases,
    prediction_attempts,
    prediction_jobs,
)

OUTPUT_SCHEMA_VERSION = "quakestrike.prediction-output.v2"


class StalePredictionAttempt(RuntimeError):
    """The execution token or its lease no longer owns the job."""


@dataclass(frozen=True, slots=True)
class PredictionClaim:
    job_id: UUID
    attempt_id: UUID
    execution_id: UUID
    event_time: datetime
    features: Mapping[str, object]


class SqlAlchemyPredictionStore:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        lease_seconds: int = 900,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("Prediction lease must be positive.")
        self._session_factory = session_factory
        self._lease = timedelta(seconds=lease_seconds)
        self._clock = clock

    def claim(
        self, dispatch_id: UUID, job_id: UUID, correlation_id: UUID
    ) -> PredictionClaim | None:
        """Lock one job, validate the command, and create at most one live attempt."""

        now = self._clock()
        with self._session_factory() as session, session.begin():
            dispatch = session.execute(
                select(job_dispatches)
                .where(
                    job_dispatches.c.dispatch_id == dispatch_id,
                    job_dispatches.c.prediction_job_id == job_id,
                )
                .with_for_update()
            ).one_or_none()
            if dispatch is None or dispatch.status == "stopped":
                return None
            job = session.execute(
                select(prediction_jobs).where(prediction_jobs.c.job_id == job_id).with_for_update()
            ).one_or_none()
            if job is None or job.correlation_id != correlation_id:
                return None
            if job.status not in {"pending", "retry_wait", "running"}:
                return None
            if job.status == "retry_wait" and job.next_attempt_at > now:
                return None

            active = session.execute(
                select(prediction_attempts)
                .where(
                    prediction_attempts.c.job_id == job_id,
                    prediction_attempts.c.status == "running",
                )
                .with_for_update()
            ).one_or_none()
            if active is not None:
                if active.lease_expires_at > now:
                    return None
                session.execute(
                    update(prediction_attempts)
                    .where(prediction_attempts.c.attempt_id == active.attempt_id)
                    .values(
                        status="abandoned",
                        lease_expires_at=None,
                        finished_at=now,
                        error_code="lease_expired",
                        error_message="The prediction processing lease expired.",
                    )
                )
            elif job.status == "running":
                return None

            revision = session.execute(
                select(earthquake_event_revisions).where(
                    earthquake_event_revisions.c.event_revision_id == job.event_revision_id
                )
            ).one()
            release = session.execute(
                select(model_releases).where(
                    model_releases.c.model_release_id == job.model_release_id
                )
            ).one()
            attempt_number = session.scalar(
                select(prediction_attempts.c.attempt_number)
                .where(prediction_attempts.c.job_id == job_id)
                .order_by(prediction_attempts.c.attempt_number.desc())
                .limit(1)
            )
            attempt_id, execution_id = uuid4(), uuid4()
            session.execute(
                insert(prediction_attempts).values(
                    attempt_id=attempt_id,
                    job_id=job_id,
                    attempt_number=(attempt_number or 0) + 1,
                    status="running",
                    started_at=now,
                    lease_expires_at=now + self._lease,
                    worker_execution_id=execution_id,
                )
            )
            session.execute(
                update(prediction_jobs)
                .where(prediction_jobs.c.job_id == job_id)
                .values(status="running", next_attempt_at=None)
            )
            claim = PredictionClaim(
                job_id=job_id,
                attempt_id=attempt_id,
                execution_id=execution_id,
                event_time=revision.event_time,
                features=job.input_snapshot_json,
            )
            if (
                release.input_schema_version != INPUT_SCHEMA_VERSION
                or release.output_schema_version != OUTPUT_SCHEMA_VERSION
            ):
                self._finish_failed(
                    session, claim, now, "unsupported_schema", "The model schema is unsupported."
                )
                return None
            try:
                snapshot = create_feature_snapshot(
                    job.input_snapshot_json, input_schema_version=release.input_schema_version
                )
                if snapshot.sha256 != job.input_snapshot_hash:
                    raise ValueError("snapshot hash mismatch")
            except ValueError:
                self._finish_failed(
                    session,
                    claim,
                    now,
                    "invalid_snapshot",
                    "The stored feature snapshot is invalid.",
                )
                return None
            return claim

    def complete(self, claim: PredictionClaim, output: ForecastOutput) -> UUID | None:
        now = self._clock()
        try:
            with self._session_factory() as session, session.begin():
                self._lock_dispatch(session, claim.job_id)
                job, attempt = self._locked_owner(session, claim, now)
                revision = session.execute(
                    select(earthquake_event_revisions).where(
                        earthquake_event_revisions.c.event_revision_id == job.event_revision_id
                    )
                ).one()
                if (
                    output.window_start != revision.event_time
                    or output.window_end != revision.event_time + timedelta(hours=24)
                ):
                    self._finish_failed(
                        session,
                        claim,
                        now,
                        "invalid_output",
                        "The forecast window does not match the event.",
                    )
                    return None

                prior = session.execute(
                    select(forecasts.c.forecast_id)
                    .select_from(
                        forecasts.join(
                            prediction_jobs, forecasts.c.job_id == prediction_jobs.c.job_id
                        ).join(
                            earthquake_event_revisions,
                            prediction_jobs.c.event_revision_id
                            == earthquake_event_revisions.c.event_revision_id,
                        )
                    )
                    .where(
                        earthquake_event_revisions.c.event_id == revision.event_id,
                        earthquake_event_revisions.c.revision_number < revision.revision_number,
                        prediction_jobs.c.model_release_id == job.model_release_id,
                        prediction_jobs.c.status == "succeeded",
                    )
                    .order_by(
                        earthquake_event_revisions.c.revision_number.desc(),
                        prediction_jobs.c.requested_at.desc(),
                        prediction_jobs.c.job_id.desc(),
                    )
                    .limit(1)
                ).scalar_one_or_none()
                forecast_id = uuid4()
                session.execute(
                    insert(forecasts).values(
                        forecast_id=forecast_id,
                        job_id=claim.job_id,
                        supersedes_forecast_id=prior,
                        **asdict(output),
                    )
                )
                session.execute(
                    update(prediction_attempts)
                    .where(prediction_attempts.c.attempt_id == attempt.attempt_id)
                    .values(status="succeeded", finished_at=now, lease_expires_at=None)
                )
                session.execute(
                    update(prediction_jobs)
                    .where(prediction_jobs.c.job_id == claim.job_id)
                    .values(
                        status="succeeded",
                        completed_at=now,
                        last_error_code=None,
                        last_error_message=None,
                    )
                )
                self._stop_dispatch(session, claim.job_id, None)
                self._audit(session, job.correlation_id, claim.job_id, "succeeded", None)
                return forecast_id
        except StalePredictionAttempt:
            self._record_stale(claim.job_id)
            raise

    def fail(self, claim: PredictionClaim, code: str, message: str) -> None:
        now = self._clock()
        try:
            with self._session_factory() as session, session.begin():
                self._lock_dispatch(session, claim.job_id)
                self._locked_owner(session, claim, now)
                self._finish_failed(session, claim, now, code, message)
        except StalePredictionAttempt:
            self._record_stale(claim.job_id)
            raise

    def _locked_owner(self, session, claim: PredictionClaim, now: datetime):
        job = session.execute(
            select(prediction_jobs)
            .where(prediction_jobs.c.job_id == claim.job_id)
            .with_for_update()
        ).one()
        attempt = session.execute(
            select(prediction_attempts)
            .where(prediction_attempts.c.attempt_id == claim.attempt_id)
            .with_for_update()
        ).one()
        if (
            job.status != "running"
            or attempt.job_id != claim.job_id
            or attempt.status != "running"
            or attempt.worker_execution_id != claim.execution_id
            or attempt.lease_expires_at <= now
        ):
            raise StalePredictionAttempt("The prediction attempt no longer owns the job.")
        return job, attempt

    @staticmethod
    def _lock_dispatch(session, job_id: UUID) -> None:
        session.execute(
            select(job_dispatches.c.dispatch_id)
            .where(job_dispatches.c.prediction_job_id == job_id)
            .with_for_update()
        ).one()

    def _record_stale(self, job_id: UUID) -> None:
        with self._session_factory() as session, session.begin():
            correlation_id = session.scalar(
                select(prediction_jobs.c.correlation_id).where(prediction_jobs.c.job_id == job_id)
            )
            if correlation_id is not None:
                self._audit(session, correlation_id, job_id, "failed", "stale_execution_token")

    def _finish_failed(
        self, session, claim: PredictionClaim, now: datetime, code: str, message: str
    ) -> None:
        session.execute(
            update(prediction_attempts)
            .where(prediction_attempts.c.attempt_id == claim.attempt_id)
            .values(
                status="failed",
                finished_at=now,
                lease_expires_at=None,
                error_code=code,
                error_message=message,
            )
        )
        session.execute(
            update(prediction_jobs)
            .where(prediction_jobs.c.job_id == claim.job_id)
            .values(
                status="failed",
                completed_at=now,
                next_attempt_at=None,
                last_error_code=code,
                last_error_message=message,
            )
        )
        self._stop_dispatch(session, claim.job_id, code)
        correlation_id = session.scalar(
            select(prediction_jobs.c.correlation_id).where(prediction_jobs.c.job_id == claim.job_id)
        )
        self._audit(session, correlation_id, claim.job_id, "failed", code)

    @staticmethod
    def _stop_dispatch(session, job_id: UUID, reason: str | None) -> None:
        session.execute(
            update(job_dispatches)
            .where(job_dispatches.c.prediction_job_id == job_id)
            .values(
                status="stopped",
                next_dispatch_at=None,
                lease_expires_at=None,
                dispatch_token=None,
                last_error=reason,
                updated_at=datetime.now(UTC),
            )
        )

    @staticmethod
    def _audit(
        session, correlation_id: UUID, job_id: UUID, outcome: str, reason: str | None
    ) -> None:
        session.execute(
            insert(audit_logs).values(
                audit_id=uuid4(),
                actor_type="system",
                actor_service="prediction-worker",
                action="forecast_completed",
                target_type="prediction_job",
                target_id=str(job_id),
                outcome=outcome,
                reason_code=reason,
                correlation_id=correlation_id,
            )
        )
