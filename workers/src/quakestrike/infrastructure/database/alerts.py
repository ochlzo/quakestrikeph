"""Fenced, paged recipient resolution over approved worker database grants."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from quakestrike.application.alerts import AlertClaim, AlertClaimLost
from quakestrike.infrastructure.database.tables import (
    alert_jobs,
    alert_recipients,
    earthquake_event_revisions,
    forecasts,
    job_dispatches,
    prediction_jobs,
    users,
)

ACCOUNT_COLUMNS = (
    "user_id",
    "email",
    "email_verified_at",
    "email_enabled",
    "mobile_number",
    "mobile_verified_at",
    "sms_enabled",
    "alert_trigger_magnitude",
    "nearby_alerts_only",
    "alert_location_latitude",
    "alert_location_longitude",
    "alert_trigger_distance_km",
    "account_status",
    "onboarding_completed_at",
)
ALERT_TERMINAL = ("completed", "failed", "expired")


class SqlAlchemyAlertStore:
    def __init__(
        self,
        session_factory,
        *,
        clock=None,
        lease_seconds=900,
        page_size=100,
        token_factory=uuid4,
    ):
        if lease_seconds <= 0 or not 1 <= page_size <= 1000:
            raise ValueError("Alert lease and page size must be bounded positive values.")
        self.sessions = session_factory
        self.clock = clock
        self.lease = timedelta(seconds=lease_seconds)
        self.page_size = page_size
        self.token_factory = token_factory

    def _now(self, session):
        return (
            self.clock()
            if self.clock is not None
            else session.scalar(select(func.clock_timestamp()))
        )

    def claim(self, dispatch_id, alert_job_id, correlation_id):
        with self.sessions() as session, session.begin():
            dispatch = session.execute(
                select(job_dispatches)
                .where(
                    job_dispatches.c.dispatch_id == dispatch_id,
                    job_dispatches.c.alert_job_id == alert_job_id,
                )
                .with_for_update()
            ).one_or_none()
            if dispatch is None or dispatch.status not in ("dispatching", "enqueued"):
                return "rejected"
            job = session.execute(
                select(alert_jobs)
                .where(
                    alert_jobs.c.alert_job_id == alert_job_id,
                    alert_jobs.c.correlation_id == correlation_id,
                )
                .with_for_update()
            ).one_or_none()
            if job is None:
                return "rejected"
            now = self._now(session)
            if job.status in ALERT_TERMINAL:
                return job.status
            if job.expires_at <= now:
                self._settle(session, alert_job_id, dispatch_id, "expired", now)
                return "expired"
            if job.recipient_resolution_completed_at is not None:
                return "already_resolved"
            if job.lease_expires_at is not None and job.lease_expires_at > now:
                return "busy"
            if (
                job.email_body_snapshot is None
                or job.content_provenance_snapshot is None
                or job.recipient_policy_snapshot.get("version") != "automatic_forecast_alert_v1"
            ):
                self._settle(session, alert_job_id, dispatch_id, "failed", now)
                return "failed"
            anchor = session.execute(
                select(
                    earthquake_event_revisions.c.magnitude,
                    earthquake_event_revisions.c.latitude,
                    earthquake_event_revisions.c.longitude,
                )
                .select_from(
                    forecasts.join(
                        prediction_jobs, prediction_jobs.c.job_id == forecasts.c.job_id
                    ).join(
                        earthquake_event_revisions,
                        earthquake_event_revisions.c.event_revision_id
                        == prediction_jobs.c.event_revision_id,
                    )
                )
                .where(forecasts.c.forecast_id == job.forecast_id)
            ).one()
            token = self.token_factory()
            scan_through = session.scalar(
                select(users.c.user_id).order_by(users.c.user_id.desc()).limit(1)
            )
            now = self._now(session)
            if job.expires_at <= now:
                self._settle(session, alert_job_id, dispatch_id, "expired", now)
                return "expired"
            session.execute(
                update(alert_jobs)
                .where(alert_jobs.c.alert_job_id == alert_job_id)
                .values(
                    status="resolving",
                    worker_execution_id=token,
                    lease_expires_at=min(now + self.lease, job.expires_at),
                )
            )
            return AlertClaim(
                dispatch_id,
                alert_job_id,
                correlation_id,
                token,
                float(anchor.magnitude),
                float(anchor.latitude),
                float(anchor.longitude),
                scan_through,
            )

    def candidate_page(self, claim, after):
        if claim.scan_through is None:
            return ()
        with self.sessions() as session:
            query = (
                select(*(users.c[name] for name in ACCOUNT_COLUMNS))
                .where(users.c.user_id <= claim.scan_through)
                .order_by(users.c.user_id)
            )
            if after is not None:
                query = query.where(users.c.user_id > after)
            return session.execute(query.limit(self.page_size)).mappings().all()

    def _owned(self, session, claim):
        job = session.execute(
            select(alert_jobs)
            .where(
                alert_jobs.c.alert_job_id == claim.alert_job_id,
                alert_jobs.c.status == "resolving",
                alert_jobs.c.worker_execution_id == claim.token,
            )
            .with_for_update()
        ).one_or_none()
        # Sample the clock after acquiring the lock; waiting cannot extend ownership.
        now = self._now(session)
        if job is None or job.lease_expires_at <= now or job.expires_at <= now:
            raise AlertClaimLost("Alert resolution lease expired or changed.")
        return job, now

    def renew(self, claim):
        with self.sessions() as session, session.begin():
            job, now = self._owned(session, claim)
            session.execute(
                update(alert_jobs)
                .where(alert_jobs.c.alert_job_id == claim.alert_job_id)
                .values(lease_expires_at=min(now + self.lease, job.expires_at))
            )

    def record(self, claim, recipients):
        with self.sessions() as session, session.begin():
            job, now = self._owned(session, claim)
            for recipient in recipients:
                session.execute(
                    insert(alert_recipients)
                    .values(
                        recipient_id=uuid4(),
                        alert_job_id=claim.alert_job_id,
                        user_id=recipient["user_id"],
                        channel=recipient["channel"],
                        destination_snapshot=recipient["destination"],
                        eligibility_snapshot=recipient["evidence"],
                        resolved_at=now,
                        delivery_idempotency_key=(
                            f"{claim.alert_job_id}:{recipient['user_id']}:{recipient['channel']}"
                        ),
                    )
                    .on_conflict_do_nothing()
                )
            if min(job.lease_expires_at, job.expires_at) <= self._now(session):
                raise AlertClaimLost("Alert resolution lease expired before page commit.")

    def complete(self, claim):
        with self.sessions() as session, session.begin():
            # Dispatch precedes job whenever both durable rows are locked.
            session.execute(
                select(job_dispatches.c.dispatch_id)
                .where(job_dispatches.c.dispatch_id == claim.dispatch_id)
                .with_for_update()
            ).one()
            job, _ = self._owned(session, claim)
            count = session.scalar(
                select(func.count())
                .select_from(alert_recipients)
                .where(alert_recipients.c.alert_job_id == claim.alert_job_id)
            )
            now = self._now(session)
            if min(job.lease_expires_at, job.expires_at) <= now:
                raise AlertClaimLost("Alert resolution lease expired before checkpoint.")
            session.execute(
                update(alert_jobs)
                .where(alert_jobs.c.alert_job_id == claim.alert_job_id)
                .values(recipient_resolution_completed_at=now)
            )
            if count:
                session.execute(
                    update(alert_jobs)
                    .where(alert_jobs.c.alert_job_id == claim.alert_job_id)
                    .values(status="delivering")
                )
            else:
                self._settle(session, claim.alert_job_id, claim.dispatch_id, "completed", now)
            if min(job.lease_expires_at, job.expires_at) <= self._now(session):
                raise AlertClaimLost("Alert resolution lease expired before checkpoint commit.")
            return bool(count)

    @staticmethod
    def _settle(session, job_id, dispatch_id, status, now):
        session.execute(
            update(alert_jobs)
            .where(alert_jobs.c.alert_job_id == job_id)
            .values(
                status=status, completed_at=now, lease_expires_at=None, worker_execution_id=None
            )
        )
        if status == "expired":
            session.execute(
                update(alert_recipients)
                .where(
                    alert_recipients.c.alert_job_id == job_id,
                    alert_recipients.c.status.in_(("pending", "retry_wait")),
                )
                .values(status="expired", next_attempt_at=None)
            )
        session.execute(
            update(job_dispatches)
            .where(job_dispatches.c.dispatch_id == dispatch_id)
            .values(
                status="stopped", next_dispatch_at=None, lease_expires_at=None, dispatch_token=None
            )
        )
