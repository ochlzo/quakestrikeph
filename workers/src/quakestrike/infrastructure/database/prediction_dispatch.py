"""PostgreSQL lifecycle for prediction queue dispatches."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select, update

from quakestrike.application.prediction_dispatch import (
    PredictionDispatch,
    PredictionDispatchClaim,
    PredictionDispatchStore,
)
from quakestrike.infrastructure.database.engine import SessionFactory
from quakestrike.infrastructure.database.tables import job_dispatches, prediction_jobs


class DispatchClaimLost(RuntimeError):
    """Raised when a dispatcher no longer owns the durable dispatch claim."""


class SqlAlchemyPredictionDispatchStore(PredictionDispatchStore):
    """Claim and finalize prediction dispatch rows in separate transactions."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        lease_seconds: int = 60,
        retry_delay_seconds: int = 30,
    ) -> None:
        if lease_seconds <= 0 or retry_delay_seconds <= 0:
            raise ValueError("Dispatch lease and retry delays must be positive.")
        self._session_factory = session_factory
        self._lease_seconds = lease_seconds
        self._retry_delay_seconds = retry_delay_seconds

    def claim(self, dispatch: PredictionDispatch) -> PredictionDispatchClaim | None:
        token = uuid4()
        now = datetime.now(UTC)
        with self._session_factory() as session, session.begin():
            row = session.execute(
                select(
                    job_dispatches.c.prediction_job_id,
                    job_dispatches.c.status,
                    job_dispatches.c.next_dispatch_at,
                    prediction_jobs.c.correlation_id,
                )
                .join(
                    prediction_jobs,
                    prediction_jobs.c.job_id == job_dispatches.c.prediction_job_id,
                )
                .where(job_dispatches.c.dispatch_id == dispatch.dispatch_id)
                .with_for_update()
            ).one_or_none()
            if row is None:
                raise ValueError("The prediction dispatch does not exist.")
            if row.prediction_job_id != dispatch.job_id:
                raise ValueError("The dispatch does not target the requested prediction job.")
            if row.correlation_id != dispatch.correlation_id:
                raise ValueError("The dispatch correlation ID does not match the prediction job.")
            if row.status not in {"pending", "retry_wait"}:
                return None
            if row.next_dispatch_at is None or row.next_dispatch_at > now:
                return None

            session.execute(
                update(job_dispatches)
                .where(job_dispatches.c.dispatch_id == dispatch.dispatch_id)
                .values(
                    status="dispatching",
                    next_dispatch_at=None,
                    lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                    dispatch_token=token,
                    attempt_count=job_dispatches.c.attempt_count + 1,
                    updated_at=func.now(),
                )
            )
        return PredictionDispatchClaim(dispatch=dispatch, token=token)

    def mark_enqueued(self, claim: PredictionDispatchClaim) -> None:
        with self._session_factory() as session, session.begin():
            result = session.execute(
                update(job_dispatches)
                .where(
                    job_dispatches.c.dispatch_id == claim.dispatch.dispatch_id,
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
                raise DispatchClaimLost("The prediction dispatch claim is no longer current.")

    def mark_retry(self, claim: PredictionDispatchClaim, error: Exception) -> None:
        with self._session_factory() as session, session.begin():
            result = session.execute(
                update(job_dispatches)
                .where(
                    job_dispatches.c.dispatch_id == claim.dispatch.dispatch_id,
                    job_dispatches.c.status == "dispatching",
                    job_dispatches.c.dispatch_token == claim.token,
                )
                .values(
                    status="retry_wait",
                    next_dispatch_at=datetime.now(UTC)
                    + timedelta(seconds=self._retry_delay_seconds),
                    lease_expires_at=None,
                    dispatch_token=None,
                    last_error=_error_summary(error),
                    updated_at=func.now(),
                )
            )
            if result.rowcount != 1:
                raise DispatchClaimLost("The prediction dispatch claim is no longer current.")


def _error_summary(error: Exception) -> str:
    detail = str(error).strip()
    if detail:
        return f"{type(error).__name__}: {detail}"[:2_000]
    return type(error).__name__
