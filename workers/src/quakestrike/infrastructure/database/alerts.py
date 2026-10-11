"""Fenced, paged recipient resolution over approved worker database grants."""

from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from quakestrike.application.alert_delivery import (
    AlertSubmission,
    SubmissionResult,
    normalize_submission,
)
from quakestrike.application.alerts import AlertClaim, AlertClaimLost
from quakestrike.domain.alerts import eligible_alert_channels
from quakestrike.infrastructure.database.tables import (
    alert_delivery_attempts,
    alert_jobs,
    alert_recipients,
    audit_logs,
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
CONTENT_ADDITIONS = (
    "email_subject_snapshot",
    "email_body_snapshot",
    "nearby_message_snapshot",
    "nearby_email_subject_snapshot",
    "nearby_email_body_snapshot",
    "content_provenance_snapshot",
)


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

    def claim(self, dispatch_id, alert_job_id, correlation_id, *, delivery=False):
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
            if job.recipient_resolution_completed_at is not None and not delivery:
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
                    status="delivering" if job.recipient_resolution_completed_at else "resolving",
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
            accounts = session.execute(query.limit(self.page_size)).mappings().all()
            existing = session.execute(
                select(alert_recipients.c.user_id, alert_recipients.c.channel).where(
                    alert_recipients.c.alert_job_id == claim.alert_job_id,
                    alert_recipients.c.user_id.in_([account["user_id"] for account in accounts]),
                )
            ).all()
            return [
                {
                    **account,
                    "resolved_channels": {
                        row.channel for row in existing if row.user_id == account["user_id"]
                    },
                }
                for account in accounts
            ]

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
                unsupported = (
                    recipient["channel"] == "sms"
                    and recipient["evidence"].get("ordinary_sms_supported") is False
                )
                session.execute(
                    insert(alert_recipients)
                    .values(
                        recipient_id=uuid4(),
                        alert_job_id=claim.alert_job_id,
                        user_id=recipient["user_id"],
                        channel=recipient["channel"],
                        destination_snapshot=recipient["destination"],
                        eligibility_snapshot=recipient["evidence"],
                        status="skipped" if unsupported else "pending",
                        last_error_code="sms_sender_unsupported" if unsupported else None,
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
                .where(
                    alert_recipients.c.alert_job_id == claim.alert_job_id,
                    alert_recipients.c.status.in_(
                        ("pending", "retry_wait", "sending", "accepted", "unknown")
                    ),
                )
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

    def _delivery_owned(self, session, claim):
        job = session.execute(
            select(alert_jobs)
            .where(
                alert_jobs.c.alert_job_id == claim.alert_job_id,
                alert_jobs.c.correlation_id == claim.correlation_id,
                alert_jobs.c.status.in_(("resolving", "delivering")),
                alert_jobs.c.worker_execution_id == claim.token,
            )
            .with_for_update()
        ).one_or_none()
        now = self._now(session)
        if job is None or min(job.lease_expires_at, job.expires_at) <= now:
            raise AlertClaimLost("Alert delivery lease expired or changed.")
        return job, now

    def renew_delivery(self, claim):
        with self.sessions() as session, session.begin():
            job, now = self._delivery_owned(session, claim)
            session.execute(
                update(alert_jobs)
                .where(alert_jobs.c.alert_job_id == claim.alert_job_id)
                .values(lease_expires_at=min(now + self.lease, job.expires_at))
            )

    def due_recipients(self, claim, limit):
        with self.sessions() as session, session.begin():
            _, now = self._delivery_owned(session, claim)
            return session.execute(
                select(alert_recipients)
                .where(
                    alert_recipients.c.alert_job_id == claim.alert_job_id,
                    or_(
                        alert_recipients.c.status == "pending",
                        and_(
                            alert_recipients.c.status == "retry_wait",
                            alert_recipients.c.next_attempt_at <= now,
                        ),
                    ),
                )
                .order_by(alert_recipients.c.recipient_id)
                .limit(limit)
            ).all()

    def begin_submission(self, claim, recipient_id, supported):
        with self.sessions() as session, session.begin():
            job, now = self._delivery_owned(session, claim)
            recipient = session.execute(
                select(alert_recipients)
                .where(
                    alert_recipients.c.recipient_id == recipient_id,
                    alert_recipients.c.alert_job_id == claim.alert_job_id,
                )
                .with_for_update()
            ).one()
            if recipient.status not in ("pending", "retry_wait") or (
                recipient.next_attempt_at is not None and recipient.next_attempt_at > now
            ):
                return None
            account = (
                session.execute(
                    select(*(users.c[name] for name in ACCOUNT_COLUMNS)).where(
                        users.c.user_id == recipient.user_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            candidates = (
                eligible_alert_channels(account, claim.magnitude, claim.latitude, claim.longitude)
                if account
                else []
            )
            candidate = next(
                (
                    item
                    for item in candidates
                    if item["channel"] == recipient.channel
                    and item["destination"] == recipient.destination_snapshot
                ),
                None,
            )
            if candidate is None or supported is False:
                session.execute(
                    update(alert_recipients)
                    .where(alert_recipients.c.recipient_id == recipient_id)
                    .values(
                        status="skipped", next_attempt_at=None, last_error_code="lost_eligibility"
                    )
                )
                return None
            if supported is None:
                session.execute(
                    update(alert_recipients)
                    .where(alert_recipients.c.recipient_id == recipient_id)
                    .values(
                        status="retry_wait",
                        next_attempt_at=now + timedelta(seconds=60),
                        last_error_code="sms_support_unavailable",
                    )
                )
                return None
            variant = "nearby" if candidate["evidence"]["nearby_alerts_only"] else "general"
            attempt_id, token = uuid4(), self.token_factory()
            now = self._now(session)
            if min(job.lease_expires_at, job.expires_at) <= now:
                raise AlertClaimLost("Alert expired before attempt creation.")
            number = (
                session.scalar(
                    select(
                        func.coalesce(func.max(alert_delivery_attempts.c.attempt_number), 0)
                    ).where(alert_delivery_attempts.c.recipient_id == recipient_id)
                )
                + 1
            )
            evidence = {
                **candidate["evidence"],
                "checked_at": now.isoformat(),
                "expires_at": job.expires_at.isoformat(),
            }
            if recipient.channel == "sms":
                evidence["ordinary_sms_supported"] = True
            session.execute(
                insert(alert_delivery_attempts).values(
                    delivery_attempt_id=attempt_id,
                    recipient_id=recipient_id,
                    attempt_number=number,
                    provider="iprog" if recipient.channel == "sms" else "brevo",
                    status="sending",
                    started_at=now,
                    correlation_id=claim.correlation_id,
                    content_variant=variant,
                    eligibility_snapshot=evidence,
                )
            )
            session.execute(
                update(alert_recipients)
                .where(alert_recipients.c.recipient_id == recipient_id)
                .values(
                    status="sending",
                    next_attempt_at=None,
                    worker_execution_id=token,
                    processing_lease_expires_at=now + self.lease,
                )
            )
            if recipient.channel == "sms":
                body = job.nearby_message_snapshot if variant == "nearby" else job.message_snapshot
                subject = None
            else:
                body = (
                    job.nearby_email_body_snapshot
                    if variant == "nearby"
                    else job.email_body_snapshot
                )
                subject = (
                    job.nearby_email_subject_snapshot
                    if variant == "nearby"
                    else job.email_subject_snapshot
                )
            return AlertSubmission(
                attempt_id,
                recipient_id,
                token,
                recipient.channel,
                recipient.destination_snapshot,
                body,
                subject,
            )

    def finish_submission(self, request, result):
        with self.sessions() as session, session.begin():
            recipient = session.execute(
                select(alert_recipients)
                .where(alert_recipients.c.recipient_id == request.recipient_id)
                .with_for_update()
            ).one()
            attempt = session.execute(
                select(alert_delivery_attempts)
                .where(alert_delivery_attempts.c.delivery_attempt_id == request.attempt_id)
                .with_for_update()
            ).one()
            now = self._now(session)
            if attempt.recipient_id != request.recipient_id:
                return "conflict"
            if (
                attempt.provider_message_id is not None
                and result.reference is not None
                and attempt.provider_message_id != result.reference
            ):
                return "conflict"
            owned = (
                recipient.worker_execution_id == request.token
                and recipient.processing_lease_expires_at is not None
                and recipient.processing_lease_expires_at > now
                and attempt.status == "sending"
            )
            if not owned:
                # Late provider evidence cannot restore processing ownership or retry authority.
                if (
                    result.status in ("accepted", "unknown")
                    and result.reference
                    and attempt.status in ("unknown", "sending")
                ):
                    session.execute(
                        update(alert_delivery_attempts)
                        .where(alert_delivery_attempts.c.delivery_attempt_id == request.attempt_id)
                        .values(
                            status=result.status,
                            provider_message_id=result.reference,
                            finished_at=attempt.finished_at or max(now, attempt.started_at),
                            error_code=result.error_code,
                            provider_evidence_snapshot={
                                **(attempt.provider_evidence_snapshot or {}),
                                **result.evidence,
                            },
                        )
                    )
                    newer = session.scalar(
                        select(func.count())
                        .select_from(alert_delivery_attempts)
                        .where(
                            alert_delivery_attempts.c.recipient_id == request.recipient_id,
                            alert_delivery_attempts.c.attempt_number > attempt.attempt_number,
                        )
                    )
                    if not newer and recipient.status != "delivered":
                        session.execute(
                            update(alert_recipients)
                            .where(alert_recipients.c.recipient_id == request.recipient_id)
                            .values(
                                status=result.status,
                                next_attempt_at=None,
                                last_error_code=result.error_code,
                                processing_lease_expires_at=None,
                                worker_execution_id=None,
                            )
                        )
                    return "applied"
                if result.evidence:
                    session.execute(
                        update(alert_delivery_attempts)
                        .where(alert_delivery_attempts.c.delivery_attempt_id == request.attempt_id)
                        .values(
                            provider_evidence_snapshot={
                                **(attempt.provider_evidence_snapshot or {}),
                                **result.evidence,
                            }
                        )
                    )
                return "ignored"
            status = "accepted" if result.status == "accepted" and result.reference else "unknown"
            recipient_status = status
            next_attempt_at = None
            if result.status in ("transient", "permanent"):
                status = recipient_status = "failed"
                if result.status == "transient" and attempt.attempt_number < 4:
                    delays = (30, 120, 600)
                    delay = delays[attempt.attempt_number - 1]
                    if result.retry_after_seconds is not None:
                        delay = max(delay, result.retry_after_seconds)
                    expiry = session.scalar(
                        select(alert_jobs.c.expires_at).where(
                            alert_jobs.c.alert_job_id == recipient.alert_job_id
                        )
                    )
                    if delay < (expiry - now).total_seconds():
                        next_attempt_at = now + timedelta(seconds=delay)
                        recipient_status = "retry_wait"
                    else:
                        recipient_status = "expired"
                        next_attempt_at = None
            session.execute(
                update(alert_delivery_attempts)
                .where(alert_delivery_attempts.c.delivery_attempt_id == request.attempt_id)
                .values(
                    status=status,
                    provider_message_id=result.reference or attempt.provider_message_id,
                    finished_at=max(now, attempt.started_at),
                    error_code=result.error_code,
                    provider_evidence_snapshot=result.evidence,
                )
            )
            session.execute(
                update(alert_recipients)
                .where(alert_recipients.c.recipient_id == request.recipient_id)
                .values(
                    status=recipient_status,
                    next_attempt_at=next_attempt_at,
                    last_error_code=result.error_code,
                    processing_lease_expires_at=None,
                    worker_execution_id=None,
                )
            )

    def maintain(self, dispatch_id, job_id, correlation_id):
        """Recover calls and settle terminal batches without acquiring send authority."""
        with self.sessions() as session, session.begin():
            dispatch = session.execute(
                select(job_dispatches)
                .where(
                    job_dispatches.c.dispatch_id == dispatch_id,
                    job_dispatches.c.alert_job_id == job_id,
                )
                .with_for_update()
            ).one_or_none()
            job = session.execute(
                select(alert_jobs)
                .where(
                    alert_jobs.c.alert_job_id == job_id,
                    alert_jobs.c.correlation_id == correlation_id,
                )
                .with_for_update()
            ).one_or_none()
            if dispatch is None or job is None:
                return "rejected"
            now = self._now(session)
            sending = session.execute(
                select(alert_recipients)
                .where(
                    alert_recipients.c.alert_job_id == job_id,
                    alert_recipients.c.status == "sending",
                    alert_recipients.c.processing_lease_expires_at <= now,
                )
                .order_by(alert_recipients.c.recipient_id)
                .with_for_update()
            ).all()
            for recipient in sending:
                attempt = session.execute(
                    select(alert_delivery_attempts)
                    .where(
                        alert_delivery_attempts.c.recipient_id == recipient.recipient_id,
                        alert_delivery_attempts.c.status == "sending",
                    )
                    .with_for_update()
                ).one_or_none()
                if attempt:
                    session.execute(
                        update(alert_delivery_attempts)
                        .where(
                            alert_delivery_attempts.c.delivery_attempt_id
                            == attempt.delivery_attempt_id
                        )
                        .values(
                            status="unknown",
                            finished_at=max(now, attempt.started_at),
                            error_code="interrupted_call",
                        )
                    )
                session.execute(
                    update(alert_recipients)
                    .where(alert_recipients.c.recipient_id == recipient.recipient_id)
                    .values(
                        status="unknown",
                        processing_lease_expires_at=None,
                        worker_execution_id=None,
                        last_error_code="interrupted_call",
                    )
                )
            if job.status in ALERT_TERMINAL:
                return job.status
            if job.expires_at <= now:
                self._settle(session, job_id, dispatch_id, "expired", now)
                return "expired"
            unsettled = session.scalar(
                select(func.count())
                .select_from(alert_recipients)
                .where(
                    alert_recipients.c.alert_job_id == job_id,
                    alert_recipients.c.status.in_(
                        ("pending", "retry_wait", "sending", "accepted", "unknown")
                    ),
                )
            )
            if job.recipient_resolution_completed_at is not None and not unsettled:
                self._settle(session, job_id, dispatch_id, "completed", now)
                return "completed"
            return job.status

    def finish_pass(self, claim):
        """Release the root lease and schedule durable work, not a provider resend."""
        status = self.maintain(claim.dispatch_id, claim.alert_job_id, claim.correlation_id)
        if status in ALERT_TERMINAL:
            return status
        with self.sessions() as session, session.begin():
            dispatch = session.execute(
                select(job_dispatches)
                .where(
                    job_dispatches.c.dispatch_id == claim.dispatch_id,
                    job_dispatches.c.alert_job_id == claim.alert_job_id,
                )
                .with_for_update()
            ).one()
            job, now = self._delivery_owned(session, claim)
            retry = session.scalar(
                select(func.min(alert_recipients.c.next_attempt_at)).where(
                    alert_recipients.c.alert_job_id == claim.alert_job_id,
                    alert_recipients.c.status == "retry_wait",
                )
            )
            pending = session.scalar(
                select(func.count())
                .select_from(alert_recipients)
                .where(
                    alert_recipients.c.alert_job_id == claim.alert_job_id,
                    alert_recipients.c.status == "pending",
                )
            )
            due = min(retry or now + timedelta(seconds=60), now + timedelta(seconds=60))
            if pending:
                due = now + timedelta(seconds=1)
            session.execute(
                update(alert_jobs)
                .where(alert_jobs.c.alert_job_id == claim.alert_job_id)
                .values(
                    lease_expires_at=now,
                )
            )
            session.execute(
                update(job_dispatches)
                .where(job_dispatches.c.dispatch_id == dispatch.dispatch_id)
                .values(
                    status="retry_wait",
                    next_dispatch_at=due,
                    lease_expires_at=None,
                    dispatch_token=None,
                )
            )
            return job.status

    def allow_submission(self, claim, request):
        """Check exact ownership and fresh account evidence after the attempt commit."""
        with self.sessions() as session, session.begin():
            job = session.execute(
                select(alert_jobs)
                .where(
                    alert_jobs.c.alert_job_id == claim.alert_job_id,
                )
                .with_for_update()
            ).one()
            recipient = session.execute(
                select(alert_recipients)
                .where(
                    alert_recipients.c.recipient_id == request.recipient_id,
                )
                .with_for_update()
            ).one()
            attempt = session.execute(
                select(alert_delivery_attempts)
                .where(
                    alert_delivery_attempts.c.delivery_attempt_id == request.attempt_id,
                )
                .with_for_update()
            ).one()
            now = self._now(session)
            if recipient.worker_execution_id != request.token or attempt.status != "sending":
                return False
            account = (
                session.execute(
                    select(*(users.c[name] for name in ACCOUNT_COLUMNS)).where(
                        users.c.user_id == recipient.user_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            candidates = (
                eligible_alert_channels(account, claim.magnitude, claim.latitude, claim.longitude)
                if account
                else []
            )
            candidate = next(
                (
                    item
                    for item in candidates
                    if item["channel"] == request.channel
                    and item["destination"] == request.destination
                ),
                None,
            )
            eligible = candidate is not None and all(
                candidate["evidence"].get(key) == value
                for key, value in attempt.eligibility_snapshot.items()
                if key not in ("checked_at", "expires_at", "ordinary_sms_supported")
            )
            owned = (
                job.worker_execution_id == claim.token
                and job.status in ("resolving", "delivering")
                and job.lease_expires_at > now
                and recipient.processing_lease_expires_at > now
            )
            if eligible and owned and job.expires_at > now:
                return True
            expired = job.expires_at <= now
            session.execute(
                update(alert_delivery_attempts)
                .where(alert_delivery_attempts.c.delivery_attempt_id == request.attempt_id)
                .values(
                    status="failed",
                    finished_at=max(now, attempt.started_at),
                    error_code="not_submitted_expired"
                    if expired
                    else "not_submitted_settings_or_claim",
                )
            )
            session.execute(
                update(alert_recipients)
                .where(alert_recipients.c.recipient_id == request.recipient_id)
                .values(
                    status="expired" if expired else "skipped",
                    next_attempt_at=None,
                    worker_execution_id=None,
                    processing_lease_expires_at=None,
                    last_error_code="not_submitted_expired"
                    if expired
                    else "not_submitted_settings_or_claim",
                )
            )
            return False

    def iprog_poll_candidates(self, *, after=None, limit=20, alert_job_id=None):
        """Keyset pages retain late reconciliation for expired or completed batches."""
        if not 1 <= limit <= 100:
            raise ValueError("SMS poll batch must contain 1 to 100 attempts.")
        query = (
            select(
                alert_delivery_attempts.c.delivery_attempt_id,
                alert_delivery_attempts.c.provider_message_id,
                alert_jobs.c.alert_job_id,
                alert_jobs.c.correlation_id,
                job_dispatches.c.dispatch_id,
            )
            .join(
                alert_recipients,
                alert_recipients.c.recipient_id == alert_delivery_attempts.c.recipient_id,
            )
            .join(alert_jobs, alert_jobs.c.alert_job_id == alert_recipients.c.alert_job_id)
            .join(job_dispatches, job_dispatches.c.alert_job_id == alert_jobs.c.alert_job_id)
            .where(
                alert_delivery_attempts.c.provider == "iprog",
                alert_delivery_attempts.c.status.in_(("accepted", "unknown")),
                alert_delivery_attempts.c.provider_message_id.is_not(None),
            )
            .order_by(alert_delivery_attempts.c.delivery_attempt_id)
            .limit(limit)
        )
        if after is not None:
            query = query.where(alert_delivery_attempts.c.delivery_attempt_id > after)
        if alert_job_id is not None:
            query = query.where(alert_jobs.c.alert_job_id == alert_job_id)
        with self.sessions() as session:
            return session.execute(query).all()

    def maintenance_candidates(self, *, after=None, limit=20):
        """Independent keyset scan also recovers interrupted calls on terminal jobs."""
        if not 1 <= limit <= 100:
            raise ValueError("Alert maintenance batch must contain 1 to 100 jobs.")
        with self.sessions() as session:
            now = self._now(session)
            interrupted = (
                select(alert_recipients.c.recipient_id)
                .where(
                    alert_recipients.c.alert_job_id == alert_jobs.c.alert_job_id,
                    alert_recipients.c.status == "sending",
                    alert_recipients.c.processing_lease_expires_at <= now,
                )
                .exists()
            )
            query = (
                select(
                    alert_jobs.c.alert_job_id,
                    alert_jobs.c.correlation_id,
                    job_dispatches.c.dispatch_id,
                )
                .join(job_dispatches, job_dispatches.c.alert_job_id == alert_jobs.c.alert_job_id)
                .where(
                    or_(
                        and_(
                            alert_jobs.c.status.not_in(ALERT_TERMINAL),
                            or_(
                                alert_jobs.c.lease_expires_at.is_(None),
                                alert_jobs.c.lease_expires_at <= now,
                                alert_jobs.c.expires_at <= now,
                            ),
                        ),
                        interrupted,
                    )
                )
                .order_by(alert_jobs.c.alert_job_id)
                .limit(limit)
            )
            if after is not None:
                query = query.where(alert_jobs.c.alert_job_id > after)
            return session.execute(query).all()

    def preview_legacy_alerts(self, *, limit=100):
        if not 1 <= limit <= 100:
            raise ValueError("Legacy retirement preview must contain 1 to 100 jobs.")
        with self.sessions() as session:
            now = self._now(session)
            attempts = (
                select(alert_delivery_attempts.c.delivery_attempt_id)
                .join(
                    alert_recipients,
                    alert_recipients.c.recipient_id == alert_delivery_attempts.c.recipient_id,
                )
                .where(alert_recipients.c.alert_job_id == alert_jobs.c.alert_job_id)
                .exists()
            )
            evidence = (
                select(alert_recipients.c.recipient_id)
                .where(
                    alert_recipients.c.alert_job_id == alert_jobs.c.alert_job_id,
                    alert_recipients.c.status.not_in(("pending", "retry_wait")),
                )
                .exists()
            )
            rows = session.execute(
                select(alert_jobs, job_dispatches.c.dispatch_id)
                .join(
                    job_dispatches,
                    job_dispatches.c.alert_job_id == alert_jobs.c.alert_job_id,
                )
                .where(
                    *(alert_jobs.c[name].is_(None) for name in CONTENT_ADDITIONS),
                    alert_jobs.c.status.not_in(ALERT_TERMINAL),
                    ~attempts,
                    ~evidence,
                    or_(
                        alert_jobs.c.lease_expires_at.is_(None),
                        alert_jobs.c.lease_expires_at <= now,
                    ),
                    or_(
                        job_dispatches.c.lease_expires_at.is_(None),
                        job_dispatches.c.lease_expires_at <= now,
                    ),
                )
                .order_by(alert_jobs.c.alert_job_id)
                .limit(limit)
            ).all()
            return [
                {
                    "alert_job_id": str(row.alert_job_id),
                    "dispatch_id": str(row.dispatch_id),
                    "status": row.status,
                    "expires_at": row.expires_at.isoformat(),
                    "content_sha256": sha256(row.message_snapshot.encode()).hexdigest(),
                    "recipient_count": session.scalar(
                        select(func.count())
                        .select_from(alert_recipients)
                        .where(alert_recipients.c.alert_job_id == row.alert_job_id)
                    ),
                }
                for row in rows
            ]

    def retire_legacy_alerts(self, job_ids):
        """Explicitly retire only selected unsent legacy rows, including required audits."""
        job_ids = tuple(sorted(set(job_ids)))
        if not 1 <= len(job_ids) <= 100:
            raise ValueError("Select 1 to 100 legacy job IDs.")
        retired = 0
        with self.sessions() as session, session.begin():
            for job_id in job_ids:
                dispatch = session.execute(
                    select(job_dispatches)
                    .where(job_dispatches.c.alert_job_id == job_id)
                    .with_for_update()
                ).one_or_none()
                job = session.execute(
                    select(alert_jobs).where(alert_jobs.c.alert_job_id == job_id).with_for_update()
                ).one_or_none()
                if (
                    job is None
                    or dispatch is None
                    or any(job._mapping[name] is not None for name in CONTENT_ADDITIONS)
                ):
                    raise ValueError("Selected job is not applicable legacy work.")
                if job.status in ALERT_TERMINAL:
                    continue
                recipients = session.execute(
                    select(alert_recipients)
                    .where(alert_recipients.c.alert_job_id == job_id)
                    .order_by(alert_recipients.c.recipient_id)
                    .with_for_update()
                ).all()
                attempts = session.scalar(
                    select(func.count())
                    .select_from(
                        alert_delivery_attempts.join(
                            alert_recipients,
                            alert_recipients.c.recipient_id
                            == alert_delivery_attempts.c.recipient_id,
                        )
                    )
                    .where(alert_recipients.c.alert_job_id == job_id)
                )
                now = self._now(session)
                if (
                    (job.lease_expires_at is not None and job.lease_expires_at > now)
                    or (dispatch.lease_expires_at is not None and dispatch.lease_expires_at > now)
                    or attempts
                    or any(row.status not in ("pending", "retry_wait") for row in recipients)
                ):
                    raise ValueError("Selected legacy work has active claims or retained evidence.")
                terminal = "expired" if job.expires_at <= now else "failed"
                self._settle(session, job_id, dispatch.dispatch_id, terminal, now)
                if terminal == "failed":
                    session.execute(
                        update(alert_recipients)
                        .where(
                            alert_recipients.c.alert_job_id == job_id,
                            alert_recipients.c.status.in_(("pending", "retry_wait")),
                        )
                        .values(
                            status="skipped",
                            next_attempt_at=None,
                            last_error_code="legacy_content_retired",
                        )
                    )
                session.execute(
                    update(job_dispatches)
                    .where(job_dispatches.c.dispatch_id == dispatch.dispatch_id)
                    .values(last_error="legacy_content_retired", updated_at=now)
                )
                session.execute(
                    insert(audit_logs).values(
                        audit_id=uuid4(),
                        occurred_at=now,
                        actor_type="system",
                        actor_service="alert-retirement",
                        action="retire_legacy_alert",
                        target_type="alert_job",
                        target_id=str(job_id),
                        outcome="succeeded",
                        reason_code="legacy_content_retired",
                        correlation_id=job.correlation_id,
                        metadata={
                            "previous_status": job.status,
                            "status": terminal,
                            "dispatch_id": str(dispatch.dispatch_id),
                            "recipient_count": len(recipients),
                            "content_sha256": sha256(job.message_snapshot.encode()).hexdigest(),
                        },
                    )
                )
                retired += 1
        return retired

    def controlled_fixture_is_valid(self, command, user_id, destinations, *, submitting=True):
        """Read approved fields only; finite fixtures never require Clerk or account writes."""
        with self.sessions() as session:
            now = self._now(session)
            user_ids = session.scalars(select(users.c.user_id).limit(2)).all()
            if user_ids != [user_id]:
                return False
            account = session.execute(
                select(*(users.c[name] for name in ACCOUNT_COLUMNS)).where(
                    users.c.user_id == user_id
                )
            ).one()
            for channel in ("sms", "email"):
                enabled = account._mapping[f"{channel}_enabled"]
                if enabled != (channel in destinations):
                    return False
                if enabled:
                    field = "mobile_number" if channel == "sms" else "email"
                    if account._mapping[field] != destinations[channel]:
                        return False
            job = session.execute(
                select(alert_jobs)
                .join(
                    job_dispatches,
                    job_dispatches.c.alert_job_id == alert_jobs.c.alert_job_id,
                )
                .where(
                    alert_jobs.c.alert_job_id == command.alert_job_id,
                    alert_jobs.c.correlation_id == command.correlation_id,
                    job_dispatches.c.dispatch_id == command.dispatch_id,
                    job_dispatches.c.status == "enqueued" if submitting else True,
                )
            ).one_or_none()
            if job is None or any(job._mapping[name] is None for name in CONTENT_ADDITIONS):
                return False
            recipients = session.execute(
                select(alert_recipients).where(
                    alert_recipients.c.alert_job_id == command.alert_job_id,
                )
            ).all()
            if any(
                row.user_id != user_id
                or row.channel not in destinations
                or row.destination_snapshot != destinations[row.channel]
                for row in recipients
            ):
                return False
            if not submitting:
                return True
            return (
                job.status == "pending"
                and job.lease_expires_at is None
                and now - timedelta(minutes=15) <= job.requested_at <= now + timedelta(minutes=1)
                and job.expires_at > now
                and not recipients
            )

    def reconcile_delivery(
        self,
        attempt_id,
        reference,
        status,
        provider_time,
        error_code=None,
        *,
        provider=None,
        evidence=None,
    ):
        """Commit verified outcomes independently from send ownership and expiry."""
        if (
            status not in ("accepted", "delivered", "failed")
            or not isinstance(reference, str)
            or reference != reference.strip()
            or not 1 <= len(reference) <= 512
            or (provider_time is not None and provider_time.tzinfo is None)
        ):
            raise ValueError("Invalid normalized delivery outcome.")
        if error_code is not None and error_code not in (
            "provider_rejected",
            "provider_failure",
            "provider_credentials_or_credit",
            "provider_permanent_rejection",
        ):
            error_code = "provider_failure"
        rank = {"sending": 0, "unknown": 0, "accepted": 1, "failed": 2, "delivered": 3}
        with self.sessions() as session, session.begin():
            link = session.execute(
                select(alert_delivery_attempts.c.recipient_id).where(
                    alert_delivery_attempts.c.delivery_attempt_id == attempt_id
                )
            ).one_or_none()
            if link is None:
                return "uncorrelated"
            recipient = session.execute(
                select(alert_recipients)
                .where(alert_recipients.c.recipient_id == link.recipient_id)
                .with_for_update()
            ).one()
            attempt = session.execute(
                select(alert_delivery_attempts)
                .where(alert_delivery_attempts.c.delivery_attempt_id == attempt_id)
                .with_for_update()
            ).one()
            if provider is not None and attempt.provider != provider:
                return "conflict"
            if attempt.provider_message_id is not None and attempt.provider_message_id != reference:
                return "conflict"
            safe_evidence = dict(attempt.provider_evidence_snapshot or {})
            if evidence is not None:
                safe_evidence.update(
                    normalize_submission(SubmissionResult("unknown", evidence=evidence)).evidence
                )
            if attempt.status == "delivered" or (
                attempt.status == "failed" and status == "accepted"
            ):
                return "ignored"
            if provider_time is None and rank[status] <= rank[attempt.status]:
                if status == attempt.status and evidence is not None:
                    session.execute(
                        update(alert_delivery_attempts)
                        .where(alert_delivery_attempts.c.delivery_attempt_id == attempt_id)
                        .values(provider_evidence_snapshot=safe_evidence)
                    )
                return "ignored"
            if (
                provider_time is not None
                and attempt.provider_status_at is not None
                and (
                    provider_time < attempt.provider_status_at
                    or (
                        provider_time == attempt.provider_status_at
                        and rank[status] <= rank[attempt.status]
                    )
                )
            ):
                return "ignored"
            now = self._now(session)
            error = (error_code or "provider_rejected") if status == "failed" else None
            session.execute(
                update(alert_delivery_attempts)
                .where(alert_delivery_attempts.c.delivery_attempt_id == attempt_id)
                .values(
                    status=status,
                    provider_message_id=reference,
                    finished_at=attempt.finished_at or max(now, attempt.started_at),
                    provider_status_at=provider_time or attempt.provider_status_at,
                    error_code=error,
                    error_message=None,
                    provider_evidence_snapshot=safe_evidence,
                )
            )
            newer = session.scalar(
                select(func.count())
                .select_from(alert_delivery_attempts)
                .where(
                    alert_delivery_attempts.c.recipient_id == recipient.recipient_id,
                    alert_delivery_attempts.c.attempt_number > attempt.attempt_number,
                )
            )
            if recipient.status != "delivered" and (status == "delivered" or not newer):
                session.execute(
                    update(alert_recipients)
                    .where(alert_recipients.c.recipient_id == recipient.recipient_id)
                    .values(
                        status=status,
                        delivered_at=(provider_time or now) if status == "delivered" else None,
                        next_attempt_at=None,
                        worker_execution_id=None,
                        processing_lease_expires_at=None,
                        last_error_code=error,
                    )
                )
            return "applied"
