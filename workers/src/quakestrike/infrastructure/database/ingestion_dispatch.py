"""PostgreSQL lifecycle for durable ingestion queue dispatches."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update

from quakestrike.application.ingestion_dispatch import (
    DispatchClaimLost,
    DispatchState,
    IngestionDispatch,
    IngestionDispatchClaim,
    IngestionDispatchStore,
)
from quakestrike.infrastructure.database.engine import SessionFactory
from quakestrike.infrastructure.database.tables import ingestion_runs, job_dispatches
from quakestrike.infrastructure.logging.json_logging import safe_exception_type

DISPATCH_ATTEMPTS_EXHAUSTED = "dispatch attempts exhausted"
DISPATCH_EXHAUSTED_ERROR_CODE = "dispatch_exhausted"
DISPATCH_TARGET_TERMINAL = "dispatch target terminal"


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


class SqlAlchemyIngestionDispatchStore(IngestionDispatchStore):
    """Claim due ingestion rows and finalize them in separate transactions."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        lease_seconds: int = 60,
        retry_delays_seconds: Sequence[int] = (30, 120, 600),
        clock: Callable[[], datetime] = _utc_now,
        token_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        retry_delays = tuple(retry_delays_seconds)
        if lease_seconds <= 0 or not retry_delays or any(delay <= 0 for delay in retry_delays):
            raise ValueError("Dispatch lease and retry delays must be positive.")
        self._session_factory = session_factory
        self._lease_seconds = lease_seconds
        self._retry_delays = tuple(timedelta(seconds=delay) for delay in retry_delays)
        self._clock = clock
        self._token_factory = token_factory

    def claim_due(
        self,
        limit: int,
        *,
        now: datetime | None = None,
    ) -> tuple[IngestionDispatchClaim, ...]:
        if limit <= 0:
            raise ValueError("Dispatcher claim limit must be positive.")
        claimed_at = self._clock() if now is None else now
        submission_is_due = or_(
            and_(
                job_dispatches.c.status.in_(("pending", "retry_wait")),
                job_dispatches.c.next_dispatch_at <= claimed_at,
            ),
            and_(
                job_dispatches.c.status == "dispatching",
                job_dispatches.c.lease_expires_at <= claimed_at,
            ),
        )
        claim_is_due = or_(
            and_(submission_is_due, _run_is_dispatch_eligible(claimed_at)),
            and_(
                job_dispatches.c.status == "enqueued",
                _processing_recovery_is_due(claimed_at),
            ),
        )

        claims: list[IngestionDispatchClaim] = []
        with self._session_factory() as session, session.begin():
            terminal_rows = session.execute(
                select(job_dispatches.c.dispatch_id, job_dispatches.c.status)
                .join(
                    ingestion_runs,
                    ingestion_runs.c.run_id == job_dispatches.c.ingestion_run_id,
                )
                .where(
                    job_dispatches.c.ingestion_run_id.is_not(None),
                    or_(submission_is_due, job_dispatches.c.status == "enqueued"),
                    ingestion_runs.c.status.in_(("succeeded", "failed", "cancelled")),
                )
                .with_for_update(of=[job_dispatches, ingestion_runs], skip_locked=True)
                .limit(limit)
            ).all()
            for row in terminal_rows:
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
                        last_error=DISPATCH_TARGET_TERMINAL,
                        updated_at=func.now(),
                    )
                )

            rows = session.execute(
                select(
                    job_dispatches.c.dispatch_id,
                    job_dispatches.c.ingestion_run_id,
                    job_dispatches.c.status,
                    job_dispatches.c.attempt_count,
                    ingestion_runs.c.correlation_id,
                )
                .join(
                    ingestion_runs,
                    ingestion_runs.c.run_id == job_dispatches.c.ingestion_run_id,
                )
                .where(job_dispatches.c.ingestion_run_id.is_not(None), claim_is_due)
                .order_by(
                    func.coalesce(
                        job_dispatches.c.next_dispatch_at,
                        job_dispatches.c.lease_expires_at,
                    ),
                    job_dispatches.c.dispatch_id,
                )
                .with_for_update(of=[job_dispatches, ingestion_runs], skip_locked=True)
                .limit(limit)
            ).all()

            for row in rows:
                if row.attempt_count >= self.max_attempts:
                    self._stop_exhausted(
                        session,
                        row.dispatch_id,
                        row.ingestion_run_id,
                        row.status,
                        claimed_at,
                    )
                    continue

                token = self._token_factory()
                result = session.execute(
                    update(job_dispatches)
                    .where(
                        job_dispatches.c.dispatch_id == row.dispatch_id,
                        job_dispatches.c.status == row.status,
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
                    raise DispatchClaimLost("The ingestion dispatch claim could not be recorded.")
                claims.append(
                    IngestionDispatchClaim(
                        dispatch=IngestionDispatch(
                            dispatch_id=row.dispatch_id,
                            run_id=row.ingestion_run_id,
                            correlation_id=row.correlation_id,
                        ),
                        token=token,
                    )
                )
        return tuple(claims)

    @property
    def max_attempts(self) -> int:
        """Return the initial attempt plus one attempt per configured retry delay."""

        return len(self._retry_delays) + 1

    def mark_enqueued(self, claim: IngestionDispatchClaim) -> None:
        with self._session_factory() as session, session.begin():
            result = session.execute(
                update(job_dispatches)
                .where(
                    job_dispatches.c.dispatch_id == claim.dispatch.dispatch_id,
                    job_dispatches.c.ingestion_run_id == claim.dispatch.run_id,
                    job_dispatches.c.status == "dispatching",
                    job_dispatches.c.dispatch_token == claim.token,
                )
                .values(
                    status="enqueued",
                    next_dispatch_at=None,
                    last_dispatched_at=func.now(),
                    lease_expires_at=None,
                    dispatch_token=None,
                    last_error=None,
                    updated_at=func.now(),
                )
            )
            if result.rowcount != 1:
                raise DispatchClaimLost("The ingestion dispatch claim is no longer current.")

    def mark_retry(
        self,
        claim: IngestionDispatchClaim,
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
                    job_dispatches.c.ingestion_run_id == claim.dispatch.run_id,
                    job_dispatches.c.status == "dispatching",
                    job_dispatches.c.dispatch_token == claim.token,
                )
                .with_for_update()
            ).one_or_none()
            if row is None:
                raise DispatchClaimLost("The ingestion dispatch claim is no longer current.")

            if 1 <= row.attempt_count <= len(self._retry_delays):
                state: DispatchState = "retry_wait"
                next_dispatch_at = retried_at + self._retry_delays[row.attempt_count - 1]
            else:
                state = "stopped"
                next_dispatch_at = None

            result = session.execute(
                update(job_dispatches)
                .where(
                    job_dispatches.c.dispatch_id == claim.dispatch.dispatch_id,
                    job_dispatches.c.ingestion_run_id == claim.dispatch.run_id,
                    job_dispatches.c.status == "dispatching",
                    job_dispatches.c.dispatch_token == claim.token,
                )
                .values(
                    status=state,
                    next_dispatch_at=next_dispatch_at,
                    lease_expires_at=None,
                    dispatch_token=None,
                    last_error=safe_exception_type(error),
                    updated_at=func.now(),
                )
            )
            if result.rowcount != 1:
                raise DispatchClaimLost("The ingestion dispatch claim is no longer current.")
            if state == "stopped":
                self._fail_run_after_exhaustion(session, claim.dispatch.run_id, retried_at)
        return state

    @staticmethod
    def _stop_exhausted(
        session,
        dispatch_id: UUID,
        run_id: UUID,
        dispatch_status: str,
        now: datetime,
    ) -> None:
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
                last_error=DISPATCH_ATTEMPTS_EXHAUSTED,
                updated_at=func.now(),
            )
        )
        SqlAlchemyIngestionDispatchStore._fail_run_after_exhaustion(session, run_id, now)

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
