"""PostgreSQL lifecycle for all durable queue-submission targets."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update

from quakestrike.application.dispatch import (
    DispatchClaim,
    DispatchClaimLost,
    DispatchState,
    DispatchStore,
    IngestionDispatch,
    PredictionDispatch,
)
from quakestrike.domain.prediction import PREDICTION_PROCESSING_LEASE_SECONDS
from quakestrike.infrastructure.database.engine import SessionFactory
from quakestrike.infrastructure.database.prediction import SqlAlchemyPredictionStore
from quakestrike.infrastructure.database.tables import (
    ingestion_runs,
    job_dispatches,
    prediction_attempts,
    prediction_jobs,
)
from quakestrike.infrastructure.logging.json_logging import safe_exception_type

DISPATCH_ATTEMPTS_EXHAUSTED = "dispatch attempts exhausted"
DISPATCH_EXHAUSTED_ERROR_CODE = "dispatch_exhausted"
DISPATCH_INVALID_ERROR_CODE = "dispatch_invalid"
DISPATCH_TARGET_TERMINAL = "dispatch target terminal"
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _processing_recovery_is_due(now: datetime):
    return or_(
        and_(
            ingestion_runs.c.status == "retry_wait",
            ingestion_runs.c.next_attempt_at <= now,
            ingestion_runs.c.lease_expires_at.is_(None),
        ),
        and_(
            ingestion_runs.c.status == "running",
            ingestion_runs.c.next_attempt_at.is_(None),
            ingestion_runs.c.lease_expires_at <= now,
        ),
    )


def _run_is_dispatch_eligible(now: datetime):
    return or_(
        and_(
            ingestion_runs.c.status == "pending",
            ingestion_runs.c.next_attempt_at.is_(None),
            ingestion_runs.c.lease_expires_at.is_(None),
        ),
        _processing_recovery_is_due(now),
    )


def _run_processing_recovery_is_due(run, now: datetime) -> bool:
    return (
        run.status == "retry_wait"
        and run.next_attempt_at is not None
        and run.next_attempt_at <= now
        and run.lease_expires_at is None
    ) or (
        run.status == "running"
        and run.next_attempt_at is None
        and run.lease_expires_at is not None
        and run.lease_expires_at <= now
    )


def _run_dispatch_is_eligible(run, dispatch_status: str, now: datetime) -> bool:
    if dispatch_status == "enqueued":
        return _run_processing_recovery_is_due(run, now)
    return (
        run.status == "pending" and run.next_attempt_at is None and run.lease_expires_at is None
    ) or _run_processing_recovery_is_due(run, now)


def _submission_is_due(now: datetime):
    return or_(
        and_(
            job_dispatches.c.status.in_(
                (
                    "pending",
                    "retry_wait",
                )
            ),
            job_dispatches.c.next_dispatch_at <= now,
        ),
        and_(
            job_dispatches.c.status == "dispatching",
            job_dispatches.c.lease_expires_at <= now,
        ),
    )


def _prediction_processing_recovery_is_due(now: datetime):
    expired_attempt = (
        select(prediction_attempts.c.attempt_id)
        .where(
            prediction_attempts.c.job_id == prediction_jobs.c.job_id,
            prediction_attempts.c.status == "running",
            prediction_attempts.c.lease_expires_at <= now,
        )
        .exists()
    )
    return or_(
        and_(
            prediction_jobs.c.status == "retry_wait",
            prediction_jobs.c.next_attempt_at <= now,
        ),
        and_(prediction_jobs.c.status == "running", expired_attempt),
    )


class SqlAlchemyDispatchStore(DispatchStore):
    """Claim and finalize ingestion and prediction dispatch rows together."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        lease_seconds: int = 60,
        retry_delays_seconds: Sequence[int] = (30, 120, 600),
        clock: Callable[[], datetime] = _utc_now,
        token_factory: Callable[[], UUID] = uuid4,
        prediction_recovery_seconds: int = PREDICTION_PROCESSING_LEASE_SECONDS,
    ) -> None:
        retry_delays = tuple(retry_delays_seconds)
        if (
            lease_seconds <= 0
            or prediction_recovery_seconds <= 0
            or not retry_delays
            or any(delay <= 0 for delay in retry_delays)
        ):
            raise ValueError("Dispatch lease and retry delays must be positive.")
        self._session_factory = session_factory
        self._lease_seconds = lease_seconds
        self._retry_delays = tuple(timedelta(seconds=delay) for delay in retry_delays)
        self._clock = clock
        self._token_factory = token_factory
        self._prediction_recovery = timedelta(seconds=prediction_recovery_seconds)

    @property
    def max_attempts(self) -> int:
        """Return the initial attempt plus one attempt per retry delay."""

        return len(self._retry_delays) + 1

    def claim_due(
        self,
        limit: int,
        *,
        now: datetime | None = None,
    ) -> tuple[DispatchClaim, ...]:
        if limit <= 0:
            raise ValueError("Dispatcher claim limit must be positive.")
        claimed_at = self._clock() if now is None else now
        submission_is_due = _submission_is_due(claimed_at)
        run_processing_recovery = _processing_recovery_is_due(claimed_at)
        run_terminal = ingestion_runs.c.status.in_(TERMINAL_STATUSES)
        prediction_terminal = prediction_jobs.c.status.in_(TERMINAL_STATUSES)
        prediction_recovery = _prediction_processing_recovery_is_due(claimed_at)
        prediction_pending = prediction_jobs.c.status == "pending"
        prediction_eligible = or_(prediction_pending, prediction_recovery)
        ingestion_candidate = and_(
            job_dispatches.c.ingestion_run_id.is_not(None),
            or_(
                and_(submission_is_due, or_(_run_is_dispatch_eligible(claimed_at), run_terminal)),
                and_(
                    job_dispatches.c.status == "enqueued",
                    or_(run_processing_recovery, run_terminal),
                ),
            ),
        )
        prediction_candidate = and_(
            job_dispatches.c.prediction_job_id.is_not(None),
            or_(
                and_(submission_is_due, or_(prediction_eligible, prediction_terminal)),
                and_(
                    job_dispatches.c.status == "enqueued",
                    or_(
                        prediction_recovery,
                        and_(
                            prediction_pending,
                            job_dispatches.c.last_dispatched_at
                            <= claimed_at - self._prediction_recovery,
                        ),
                        prediction_terminal,
                    ),
                ),
            ),
        )

        claims: list[DispatchClaim] = []
        with self._session_factory() as session, session.begin():
            rows = session.execute(
                self._select_candidates(
                    limit,
                    ingestion_candidate,
                    prediction_candidate,
                )
            ).all()
            for row in rows:
                if row.ingestion_run_id is not None:
                    run = session.execute(
                        select(ingestion_runs)
                        .where(ingestion_runs.c.run_id == row.ingestion_run_id)
                        .with_for_update(skip_locked=True)
                    ).one_or_none()
                    if run is None:
                        continue
                    if run.status in TERMINAL_STATUSES:
                        self._stop_target_terminal(session, row.dispatch_id, row.status)
                        continue
                    if not _run_dispatch_is_eligible(run, row.status, claimed_at):
                        continue
                    target = IngestionDispatch(
                        dispatch_id=row.dispatch_id,
                        run_id=row.ingestion_run_id,
                        correlation_id=run.correlation_id,
                    )
                elif row.prediction_job_id is not None:
                    prediction_job = session.execute(
                        select(prediction_jobs)
                        .where(prediction_jobs.c.job_id == row.prediction_job_id)
                        .with_for_update(skip_locked=True)
                    ).one_or_none()
                    if prediction_job is None:
                        continue
                    if prediction_job.status in TERMINAL_STATUSES:
                        self._stop_target_terminal(session, row.dispatch_id, row.status)
                        continue
                    active_attempt = session.execute(
                        select(prediction_attempts)
                        .where(
                            prediction_attempts.c.job_id == row.prediction_job_id,
                            prediction_attempts.c.status == "running",
                        )
                        .with_for_update()
                    ).one_or_none()
                    if (
                        prediction_job.status == "running"
                        and active_attempt is not None
                        and active_attempt.lease_expires_at <= claimed_at
                    ):
                        SqlAlchemyPredictionStore.recover_expired(
                            session, prediction_job, active_attempt, claimed_at
                        )
                        continue
                    if not self._prediction_dispatch_is_eligible(
                        prediction_job, active_attempt, row, claimed_at
                    ):
                        continue
                    target = PredictionDispatch(
                        dispatch_id=row.dispatch_id,
                        job_id=row.prediction_job_id,
                        correlation_id=prediction_job.correlation_id,
                    )
                else:
                    continue

                if row.attempt_count >= self.max_attempts:
                    self._stop_exhausted(session, row, claimed_at)
                    continue

                token = self._token_factory()
                result = session.execute(
                    update(job_dispatches)
                    .where(
                        job_dispatches.c.dispatch_id == row.dispatch_id,
                        job_dispatches.c.status == row.status,
                        self._target_match(target),
                    )
                    .values(
                        status="dispatching",
                        next_dispatch_at=None,
                        lease_expires_at=claimed_at + timedelta(seconds=self._lease_seconds),
                        dispatch_token=token,
                        attempt_count=job_dispatches.c.attempt_count + 1,
                        last_error=None,
                        updated_at=func.now(),
                    )
                )
                if result.rowcount != 1:
                    raise DispatchClaimLost("The dispatch claim could not be recorded.")
                claims.append(DispatchClaim(dispatch=target, token=token))
        return tuple(claims)

    def _prediction_dispatch_is_eligible(self, job, active_attempt, dispatch, now):
        if active_attempt is not None and active_attempt.lease_expires_at > now:
            return False
        if job.status == "pending":
            return dispatch.status != "enqueued" or (
                dispatch.last_dispatched_at is not None
                and dispatch.last_dispatched_at <= now - self._prediction_recovery
            )
        if job.status == "retry_wait":
            return job.next_attempt_at is not None and job.next_attempt_at <= now
        return job.status == "running" and active_attempt is not None

    def _select_candidates(
        self,
        limit: int,
        ingestion_candidate,
        prediction_candidate,
    ):
        source = job_dispatches.outerjoin(
            ingestion_runs,
            ingestion_runs.c.run_id == job_dispatches.c.ingestion_run_id,
        ).outerjoin(
            prediction_jobs,
            prediction_jobs.c.job_id == job_dispatches.c.prediction_job_id,
        )
        query = (
            select(
                job_dispatches.c.dispatch_id,
                job_dispatches.c.ingestion_run_id,
                job_dispatches.c.prediction_job_id,
                job_dispatches.c.status,
                job_dispatches.c.attempt_count,
                job_dispatches.c.last_dispatched_at,
                ingestion_runs.c.status.label("run_status"),
                ingestion_runs.c.correlation_id.label("ingestion_correlation_id"),
                prediction_jobs.c.status.label("prediction_status"),
                prediction_jobs.c.correlation_id.label("prediction_correlation_id"),
            )
            .select_from(source)
            .where(or_(ingestion_candidate, prediction_candidate))
            .order_by(
                func.coalesce(
                    job_dispatches.c.next_dispatch_at,
                    job_dispatches.c.lease_expires_at,
                ),
                job_dispatches.c.dispatch_id,
            )
            .with_for_update(
                of=[job_dispatches],
                skip_locked=True,
            )
            .limit(limit)
        )
        return query

    def mark_enqueued(self, claim: DispatchClaim) -> None:
        with self._session_factory() as session, session.begin():
            result = session.execute(
                update(job_dispatches)
                .where(
                    job_dispatches.c.dispatch_id == claim.dispatch.dispatch_id,
                    job_dispatches.c.status == "dispatching",
                    job_dispatches.c.dispatch_token == claim.token,
                    self._target_match(claim.dispatch),
                )
                .values(
                    status="enqueued",
                    attempt_count=(
                        0
                        if isinstance(claim.dispatch, PredictionDispatch)
                        else job_dispatches.c.attempt_count
                    ),
                    next_dispatch_at=None,
                    last_dispatched_at=func.now(),
                    lease_expires_at=None,
                    dispatch_token=None,
                    last_error=None,
                    updated_at=func.now(),
                )
            )
            if result.rowcount != 1:
                raise DispatchClaimLost("The dispatch claim is no longer current.")

    def mark_retry(
        self,
        claim: DispatchClaim,
        error: Exception,
        *,
        now: datetime | None = None,
    ) -> DispatchState:
        retried_at = self._clock() if now is None else now
        with self._session_factory() as session, session.begin():
            row = session.execute(
                select(job_dispatches.c.attempt_count)
                .where(
                    job_dispatches.c.dispatch_id == claim.dispatch.dispatch_id,
                    job_dispatches.c.status == "dispatching",
                    job_dispatches.c.dispatch_token == claim.token,
                    self._target_match(claim.dispatch),
                )
                .with_for_update()
            ).one_or_none()
            if row is None:
                raise DispatchClaimLost("The dispatch claim is no longer current.")

            live_until = None
            if 1 <= row.attempt_count <= len(self._retry_delays):
                state: DispatchState = "retry_wait"
                next_dispatch_at = retried_at + self._retry_delays[row.attempt_count - 1]
            else:
                state = "stopped"
                next_dispatch_at = None
                if isinstance(claim.dispatch, PredictionDispatch):
                    live_until = self._live_prediction_lease(
                        session, claim.dispatch.job_id, retried_at
                    )
                    if live_until is not None:
                        state = "retry_wait"
                        next_dispatch_at = live_until

            result = session.execute(
                update(job_dispatches)
                .where(
                    job_dispatches.c.dispatch_id == claim.dispatch.dispatch_id,
                    job_dispatches.c.status == "dispatching",
                    job_dispatches.c.dispatch_token == claim.token,
                    self._target_match(claim.dispatch),
                )
                .values(
                    status=state,
                    attempt_count=(0 if live_until is not None else job_dispatches.c.attempt_count),
                    next_dispatch_at=next_dispatch_at,
                    lease_expires_at=None,
                    dispatch_token=None,
                    last_error=safe_exception_type(error),
                    updated_at=func.now(),
                )
            )
            if result.rowcount != 1:
                raise DispatchClaimLost("The dispatch claim is no longer current.")
            if state == "stopped":
                if isinstance(claim.dispatch, IngestionDispatch):
                    self._fail_run_after_exhaustion(session, claim.dispatch.run_id, retried_at)
                else:
                    self._fail_prediction_after_dispatch_error(
                        session, claim.dispatch.job_id, retried_at, DISPATCH_EXHAUSTED_ERROR_CODE
                    )
        return state

    def mark_stopped(
        self,
        claim: DispatchClaim,
        error: Exception,
        *,
        now: datetime | None = None,
    ) -> None:
        stopped_at = self._clock() if now is None else now
        with self._session_factory() as session, session.begin():
            owned = session.execute(
                select(job_dispatches.c.dispatch_id)
                .where(
                    job_dispatches.c.dispatch_id == claim.dispatch.dispatch_id,
                    job_dispatches.c.status == "dispatching",
                    job_dispatches.c.dispatch_token == claim.token,
                    self._target_match(claim.dispatch),
                )
                .with_for_update()
            ).one_or_none()
            if owned is None:
                raise DispatchClaimLost("The dispatch claim is no longer current.")
            live_until = (
                self._live_prediction_lease(session, claim.dispatch.job_id, stopped_at)
                if isinstance(claim.dispatch, PredictionDispatch)
                else None
            )
            result = session.execute(
                update(job_dispatches)
                .where(
                    job_dispatches.c.dispatch_id == claim.dispatch.dispatch_id,
                    job_dispatches.c.status == "dispatching",
                    job_dispatches.c.dispatch_token == claim.token,
                    self._target_match(claim.dispatch),
                )
                .values(
                    status="enqueued" if live_until is not None else "stopped",
                    attempt_count=(0 if live_until is not None else job_dispatches.c.attempt_count),
                    next_dispatch_at=None,
                    lease_expires_at=None,
                    dispatch_token=None,
                    last_error=safe_exception_type(error),
                    updated_at=func.now(),
                )
            )
            if result.rowcount != 1:
                raise DispatchClaimLost("The dispatch claim is no longer current.")
            if isinstance(claim.dispatch, IngestionDispatch):
                self._fail_run_after_invalid_dispatch(session, claim.dispatch.run_id, stopped_at)
            elif live_until is None:
                self._fail_prediction_after_dispatch_error(
                    session, claim.dispatch.job_id, stopped_at, DISPATCH_INVALID_ERROR_CODE
                )

    @staticmethod
    def _live_prediction_lease(session, job_id: UUID, now: datetime) -> datetime | None:
        session.execute(
            select(prediction_jobs.c.job_id)
            .where(prediction_jobs.c.job_id == job_id)
            .with_for_update()
        ).one()
        lease_expires_at = session.scalar(
            select(prediction_attempts.c.lease_expires_at)
            .where(
                prediction_attempts.c.job_id == job_id,
                prediction_attempts.c.status == "running",
            )
            .with_for_update()
        )
        return lease_expires_at if lease_expires_at is not None and lease_expires_at > now else None

    @staticmethod
    def _target_match(dispatch):
        if isinstance(dispatch, IngestionDispatch):
            return job_dispatches.c.ingestion_run_id == dispatch.run_id
        return job_dispatches.c.prediction_job_id == dispatch.job_id

    @staticmethod
    def _stop_target_terminal(session, dispatch_id: UUID, dispatch_status: str) -> None:
        session.execute(
            update(job_dispatches)
            .where(
                job_dispatches.c.dispatch_id == dispatch_id,
                job_dispatches.c.status == dispatch_status,
            )
            .values(
                status="stopped",
                next_dispatch_at=None,
                lease_expires_at=None,
                dispatch_token=None,
                last_error=DISPATCH_TARGET_TERMINAL,
                updated_at=func.now(),
            )
        )

    def _stop_exhausted(self, session, row, now: datetime) -> None:
        session.execute(
            update(job_dispatches)
            .where(
                job_dispatches.c.dispatch_id == row.dispatch_id,
                job_dispatches.c.status == row.status,
            )
            .values(
                status="stopped",
                next_dispatch_at=None,
                lease_expires_at=None,
                dispatch_token=None,
                last_error=DISPATCH_ATTEMPTS_EXHAUSTED,
                updated_at=func.now(),
            )
        )
        if row.ingestion_run_id is not None:
            self._fail_run_after_exhaustion(session, row.ingestion_run_id, now)
        elif row.prediction_job_id is not None:
            self._fail_prediction_after_dispatch_error(
                session, row.prediction_job_id, now, DISPATCH_EXHAUSTED_ERROR_CODE
            )

    @staticmethod
    def _fail_prediction_after_dispatch_error(session, job_id: UUID, now: datetime, code: str):
        job = session.execute(
            select(prediction_jobs).where(prediction_jobs.c.job_id == job_id).with_for_update()
        ).one()
        active = session.execute(
            select(prediction_attempts)
            .where(
                prediction_attempts.c.job_id == job_id,
                prediction_attempts.c.status == "running",
            )
            .with_for_update()
        ).one_or_none()
        if active is not None and active.lease_expires_at > now:
            return
        if job.status in TERMINAL_STATUSES:
            return
        if active is not None:
            SqlAlchemyPredictionStore.abandon_expired(session, active, now)
        message = (
            DISPATCH_ATTEMPTS_EXHAUSTED
            if code == DISPATCH_EXHAUSTED_ERROR_CODE
            else "durable dispatch command is invalid"
        )
        session.execute(
            update(prediction_jobs)
            .where(prediction_jobs.c.job_id == job_id)
            .values(
                status="failed",
                next_attempt_at=None,
                completed_at=now,
                last_error_code=code,
                last_error_message=message,
            )
        )

    @staticmethod
    def _fail_run_after_exhaustion(session, run_id: UUID, now: datetime) -> None:
        session.execute(
            update(ingestion_runs)
            .where(
                ingestion_runs.c.run_id == run_id,
                _run_is_dispatch_eligible(now),
            )
            .values(
                status="failed",
                next_attempt_at=None,
                lease_expires_at=None,
                worker_execution_id=None,
                finished_at=func.now(),
                error_code=DISPATCH_EXHAUSTED_ERROR_CODE,
                error_message=DISPATCH_ATTEMPTS_EXHAUSTED,
            )
        )

    @staticmethod
    def _fail_run_after_invalid_dispatch(session, run_id: UUID, now: datetime) -> None:
        session.execute(
            update(ingestion_runs)
            .where(
                ingestion_runs.c.run_id == run_id,
                _run_is_dispatch_eligible(now),
            )
            .values(
                status="failed",
                next_attempt_at=None,
                lease_expires_at=None,
                worker_execution_id=None,
                finished_at=func.now(),
                error_code=DISPATCH_INVALID_ERROR_CODE,
                error_message="durable dispatch command is invalid",
            )
        )
