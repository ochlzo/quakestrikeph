from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from quakestrike.alert_worker.worker import handle_alert_command
from quakestrike.infrastructure.database.alerts import SqlAlchemyAlertStore
from quakestrike.infrastructure.database.tables import alert_delivery_attempts, alert_jobs

from .test_alert_resolution import Support, account, queued
from .test_prediction_worker import NOW

pytestmark = pytest.mark.integration


def test_resolved_alert_submits_frozen_channels_with_committed_attempts(migrated_engine):
    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine)
    requests = []

    class Provider:
        def submit(self, request):
            with migrated_engine.connect() as connection:
                attempt = connection.execute(
                    select(alert_delivery_attempts).where(
                        alert_delivery_attempts.c.delivery_attempt_id == request.attempt_id
                    )
                ).one()
                assert attempt.status == "sending"
                assert attempt.content_variant == "general"
                job = connection.execute(select(alert_jobs)).one()
                if request.channel == "sms":
                    assert request.body == job.message_snapshot
                else:
                    assert request.body == job.email_body_snapshot
                    assert request.subject == job.email_subject_snapshot
            requests.append(request)
            return SimpleNamespace(
                status="accepted",
                reference=f"provider-{request.attempt_id}",
                error_code=None,
                retry_after_seconds=None,
                evidence={},
            )

    assert (
        handle_alert_command(
            {
                "message_version": 1,
                "dispatch_id": str(dispatch.dispatch_id),
                "alert_job_id": str(dispatch.alert_job_id),
                "correlation_id": str(dispatch.correlation_id),
            },
            store=SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
            support=Support(),
            logger=logging.getLogger(__name__),
            providers={"email": Provider(), "sms": Provider()},
        )
        == "delivering"
    )
    assert {request.channel for request in requests} == {"email", "sms"}
    with migrated_engine.connect() as connection:
        assert {row.status for row in connection.execute(select(alert_delivery_attempts))} == {
            "accepted"
        }


@pytest.mark.parametrize(
    "outcome,expected",
    [("transient", "retry_wait"), ("permanent", "failed"), ("unknown", "unknown")],
)
def test_submission_outcomes_preserve_retry_authority(migrated_engine, outcome, expected):
    from datetime import timedelta

    from quakestrike.infrastructure.database.tables import alert_recipients

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)
    requests = []

    class Provider:
        def submit(self, request):
            requests.append(request)
            return SimpleNamespace(
                status=outcome,
                reference=None,
                error_code="provider_rejected",
                retry_after_seconds=None,
                evidence={},
            )

    payload = {
        "message_version": 1,
        "dispatch_id": str(dispatch.dispatch_id),
        "alert_job_id": str(dispatch.alert_job_id),
        "correlation_id": str(dispatch.correlation_id),
    }
    store = SqlAlchemyAlertStore(sessions, clock=lambda: NOW)
    handle_alert_command(
        payload,
        store=store,
        support=Support(),
        logger=logging.getLogger(__name__),
        providers={"email": Provider()},
    )
    with migrated_engine.connect() as connection:
        recipient = connection.execute(select(alert_recipients)).one()
        attempt = connection.execute(select(alert_delivery_attempts)).one()
        assert recipient.status == expected
        assert attempt.status == ("unknown" if outcome == "unknown" else "failed")
        assert recipient.next_attempt_at == (
            NOW + timedelta(seconds=30) if outcome == "transient" else None
        )
    handle_alert_command(
        payload,
        store=store,
        support=Support(),
        logger=logging.getLogger(__name__),
        providers={"email": Provider()},
    )
    assert len(requests) == 1


def test_due_retries_resume_completed_roster_and_stop_at_four_calls(migrated_engine):
    from datetime import timedelta

    from quakestrike.application.alert_delivery import SubmissionResult
    from quakestrike.infrastructure.database.dispatch import SqlAlchemyDispatchStore
    from quakestrike.infrastructure.database.tables import alert_recipients, job_dispatches

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)
    current = [NOW]
    requests = []

    class Provider:
        def submit(self, request):
            requests.append(request)
            return SubmissionResult("transient", error_code="provider_rejected")

    payload = {
        "message_version": 1,
        "dispatch_id": str(dispatch.dispatch_id),
        "alert_job_id": str(dispatch.alert_job_id),
        "correlation_id": str(dispatch.correlation_id),
    }
    store = SqlAlchemyAlertStore(sessions, clock=lambda: current[0])
    for offset in (0, 30, 150, 750):
        current[0] = NOW + timedelta(seconds=offset)
        if offset:
            publisher = SqlAlchemyDispatchStore(
                sessions, clock=lambda: current[0], alerts_enabled=True
            )
            claims = publisher.claim_due(10)
            assert len(claims) == 1
            publisher.mark_enqueued(claims[0])
        handle_alert_command(
            payload,
            store=store,
            support=Support(),
            logger=logging.getLogger(__name__),
            providers={"email": Provider()},
        )
    assert len(requests) == 4
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_recipients)).one().status == "failed"
        assert connection.execute(select(alert_jobs)).one().status == "completed"
        assert (
            connection.execute(
                select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch.dispatch_id)
            )
            .one()
            .status
            == "stopped"
        )
        assert [
            row.attempt_number
            for row in connection.execute(
                select(alert_delivery_attempts).order_by(alert_delivery_attempts.c.attempt_number)
            )
        ] == [1, 2, 3, 4]


def test_interrupted_call_recovers_unknown_without_resubmission(migrated_engine):
    from datetime import timedelta

    from quakestrike.infrastructure.database.dispatch import SqlAlchemyDispatchStore
    from quakestrike.infrastructure.database.tables import alert_recipients

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)
    current = [NOW]
    calls = []

    class ProcessLost(BaseException):
        pass

    class Provider:
        def submit(self, request):
            calls.append(request)
            raise ProcessLost()

    payload = {
        "message_version": 1,
        "dispatch_id": str(dispatch.dispatch_id),
        "alert_job_id": str(dispatch.alert_job_id),
        "correlation_id": str(dispatch.correlation_id),
    }
    store = SqlAlchemyAlertStore(sessions, clock=lambda: current[0], lease_seconds=60)
    with pytest.raises(ProcessLost):
        handle_alert_command(
            payload,
            store=store,
            support=Support(),
            logger=logging.getLogger(__name__),
            providers={"email": Provider()},
        )
    current[0] += timedelta(seconds=61)
    publisher = SqlAlchemyDispatchStore(sessions, clock=lambda: current[0], alerts_enabled=True)
    claims = publisher.claim_due(10)
    assert len(claims) == 1
    publisher.mark_enqueued(claims[0])
    handle_alert_command(
        payload,
        store=store,
        support=Support(),
        logger=logging.getLogger(__name__),
        providers={"email": Provider()},
    )
    assert len(calls) == 1
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_delivery_attempts)).one().status == "unknown"
        assert connection.execute(select(alert_recipients)).one().status == "unknown"


def test_late_response_after_recovery_preserves_reference_without_resend(migrated_engine):
    from datetime import timedelta

    from quakestrike.application.alert_delivery import SubmissionResult
    from quakestrike.infrastructure.database.tables import alert_recipients

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)
    current = [NOW]
    store = SqlAlchemyAlertStore(sessions, clock=lambda: current[0], lease_seconds=60)
    calls = []

    class Provider:
        def submit(self, request):
            calls.append(request)
            current[0] += timedelta(seconds=61)
            store.maintain(dispatch.dispatch_id, dispatch.alert_job_id, dispatch.correlation_id)
            return SubmissionResult("accepted", reference="late-reference")

    handle_alert_command(
        {
            "message_version": 1,
            "dispatch_id": str(dispatch.dispatch_id),
            "alert_job_id": str(dispatch.alert_job_id),
            "correlation_id": str(dispatch.correlation_id),
        },
        store=store,
        support=Support(),
        logger=logging.getLogger(__name__),
        providers={"email": Provider()},
    )
    assert len(calls) == 1
    with migrated_engine.connect() as connection:
        attempt = connection.execute(select(alert_delivery_attempts)).one()
        assert attempt.provider_message_id == "late-reference"
        assert attempt.status == "accepted"
        assert connection.execute(select(alert_recipients)).one().status == "accepted"


def test_sms_outage_checks_once_and_drains_all_committed_email(migrated_engine, caplog):
    from quakestrike.application.alert_delivery import SubmissionResult
    from quakestrike.application.alerts import SmsSupportUnavailable
    from quakestrike.infrastructure.database.tables import alert_recipients

    dispatch, sessions = queued(migrated_engine)
    for number in range(4):
        account(migrated_engine, mobile_number=f"+63917123456{number}")
    lookup_calls, sent = [], []

    class Unavailable:
        def supported(self, phone):
            lookup_calls.append(phone)
            raise SmsSupportUnavailable("sms_support_configuration")

    class Email:
        def submit(self, request):
            sent.append(request)
            return SubmissionResult("accepted", reference=str(request.attempt_id))

    caplog.set_level(logging.INFO)
    handle_alert_command(
        {
            "message_version": 1,
            "dispatch_id": str(dispatch.dispatch_id),
            "alert_job_id": str(dispatch.alert_job_id),
            "correlation_id": str(dispatch.correlation_id),
        },
        store=SqlAlchemyAlertStore(sessions, clock=lambda: NOW, page_size=2),
        support=Unavailable(),
        logger=logging.getLogger(__name__),
        providers={"email": Email()},
    )
    assert len(lookup_calls) == 1
    assert len(sent) == 4
    resolution = [
        record
        for record in caplog.records
        if getattr(record, "event_code", None) == "alert_resolution_processed"
    ]
    assert len(resolution) == 1
    assert resolution[0].context["reason"] == "sms_support_configuration"
    with migrated_engine.connect() as connection:
        job = connection.execute(select(alert_jobs)).one()
        assert job.status == "resolving"
        assert job.recipient_resolution_completed_at is None
        assert {row.channel for row in connection.execute(select(alert_recipients))} == {"email"}


def test_expiry_during_support_check_stops_unsent_work(migrated_engine):
    from datetime import timedelta

    from quakestrike.infrastructure.database.tables import alert_recipients

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, email_enabled=False)
    current = [NOW]
    calls = []

    class SupportAtExpiry:
        def supported(self, phone):
            # First lookup resolves; the next lookup is the preflight for delivery.
            calls.append(phone)
            if len(calls) == 2:
                current[0] += timedelta(days=1)
            return True

    class NoSubmission:
        def submit(self, request):
            pytest.fail("Provider submission must not start after expiry.")

    handle_alert_command(
        {
            "message_version": 1,
            "dispatch_id": str(dispatch.dispatch_id),
            "alert_job_id": str(dispatch.alert_job_id),
            "correlation_id": str(dispatch.correlation_id),
        },
        store=SqlAlchemyAlertStore(sessions, clock=lambda: current[0]),
        support=SupportAtExpiry(),
        logger=logging.getLogger(__name__),
        providers={"sms": NoSubmission()},
    )
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_jobs)).one().status == "expired"
        assert connection.execute(select(alert_recipients)).one().status == "expired"
        assert connection.execute(select(alert_delivery_attempts)).first() is None


def test_final_pre_call_recheck_closes_unsubmitted_attempt_if_settings_change(migrated_engine):
    from sqlalchemy import update

    from quakestrike.infrastructure.database.tables import alert_recipients, users

    dispatch, sessions = queued(migrated_engine)
    user_id = account(migrated_engine, sms_enabled=False)

    class ChangedAfterCommit(SqlAlchemyAlertStore):
        def begin_submission(self, *args):
            request = super().begin_submission(*args)
            if request:
                with migrated_engine.begin() as connection:
                    connection.execute(
                        update(users).where(users.c.user_id == user_id).values(email_enabled=False)
                    )
            return request

    class NoSubmission:
        def submit(self, request):
            pytest.fail("The final account check must stop this provider call.")

    handle_alert_command(
        {
            "message_version": 1,
            "dispatch_id": str(dispatch.dispatch_id),
            "alert_job_id": str(dispatch.alert_job_id),
            "correlation_id": str(dispatch.correlation_id),
        },
        store=ChangedAfterCommit(sessions, clock=lambda: NOW),
        support=Support(),
        logger=logging.getLogger(__name__),
        providers={"email": NoSubmission()},
    )
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_delivery_attempts)).one().status == "failed"
        assert connection.execute(select(alert_recipients)).one().status == "skipped"


@pytest.mark.parametrize("failure", ["transport", "bad_reference", "unsafe_evidence"])
def test_provider_boundary_normalizes_uncertainty_and_private_metadata(migrated_engine, failure):
    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)

    class Provider:
        def submit(self, request):
            if failure == "transport":
                raise TimeoutError("secret provider credential and private destination")
            return SimpleNamespace(
                status="accepted",
                reference=" bad " if failure == "bad_reference" else "safe-reference",
                error_code=None,
                retry_after_seconds=None,
                evidence={
                    "encoding": "GSM-7",
                    "token": "private secret",
                    "raw_body": "private response",
                },
            )

    handle_alert_command(
        {
            "message_version": 1,
            "dispatch_id": str(dispatch.dispatch_id),
            "alert_job_id": str(dispatch.alert_job_id),
            "correlation_id": str(dispatch.correlation_id),
        },
        store=SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
        support=Support(),
        logger=logging.getLogger(__name__),
        providers={"email": Provider()},
    )
    with migrated_engine.connect() as connection:
        attempt = connection.execute(select(alert_delivery_attempts)).one()
        assert attempt.status == ("accepted" if failure == "unsafe_evidence" else "unknown")
        assert set(attempt.provider_evidence_snapshot or {}) <= {"encoding"}
        assert "private" not in str(attempt.provider_evidence_snapshot)


def test_early_callback_delivery_wins_and_conflicting_response_is_diagnostic(
    migrated_engine, caplog
):
    from sqlalchemy import text

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)

    class Provider:
        def submit(self, request):
            with migrated_engine.begin() as connection:
                assert (
                    connection.scalar(
                        text(
                            "SELECT quakestrike_reconcile_brevo_delivery("
                            ":attempt, 'callback-reference', 'delivered', :now, NULL)"
                        ),
                        {"attempt": request.attempt_id, "now": NOW},
                    )
                    == "applied"
                )
            return SimpleNamespace(
                status="accepted",
                reference="conflicting-reference",
                error_code=None,
                retry_after_seconds=None,
                evidence={},
            )

    with caplog.at_level(logging.INFO):
        assert (
            handle_alert_command(
                {
                    "message_version": 1,
                    "dispatch_id": str(dispatch.dispatch_id),
                    "alert_job_id": str(dispatch.alert_job_id),
                    "correlation_id": str(dispatch.correlation_id),
                },
                store=SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
                support=Support(),
                logger=logging.getLogger(__name__),
                providers={"email": Provider()},
            )
            == "completed"
        )
    with migrated_engine.connect() as connection:
        attempt = connection.execute(select(alert_delivery_attempts)).one()
        assert attempt.status == "delivered" and attempt.provider_message_id == "callback-reference"
    assert any(
        getattr(record, "context", {}).get("reason") == "provider_reference_conflict"
        for record in caplog.records
    )


def test_runtime_budget_defers_remaining_roster_without_starting_more_calls(
    migrated_engine, monkeypatch
):
    import quakestrike.alert_worker.worker as worker
    from quakestrike.application.alert_delivery import SubmissionResult
    from quakestrike.infrastructure.database.tables import alert_recipients

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)
    account(migrated_engine, sms_enabled=False, mobile_number=None, mobile_verified_at=None)
    elapsed = [0]
    monkeypatch.setattr(worker, "monotonic", lambda: elapsed[0], raising=False)
    sent = []

    class Provider:
        def submit(self, request):
            sent.append(request)
            elapsed[0] = 241
            return SubmissionResult("accepted", reference=str(request.attempt_id))

    handle_alert_command(
        {
            "message_version": 1,
            "dispatch_id": str(dispatch.dispatch_id),
            "alert_job_id": str(dispatch.alert_job_id),
            "correlation_id": str(dispatch.correlation_id),
        },
        store=SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
        support=Support(),
        logger=logging.getLogger(__name__),
        providers={"email": Provider()},
    )
    assert len(sent) == 1
    with migrated_engine.connect() as connection:
        assert {row.status for row in connection.execute(select(alert_recipients))} == {
            "accepted",
            "pending",
        }


@pytest.mark.parametrize("late", [False, True])
def test_verified_delivery_settles_or_preserves_expired_job(migrated_engine, late):
    from datetime import timedelta

    from quakestrike.application.alert_delivery import SubmissionResult
    from quakestrike.infrastructure.database.tables import alert_recipients, job_dispatches

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)
    current = [NOW]
    sent = []

    class Provider:
        def submit(self, request):
            sent.append(request)
            return SubmissionResult("accepted", reference="known-reference")

    store = SqlAlchemyAlertStore(sessions, clock=lambda: current[0])
    handle_alert_command(
        {
            "message_version": 1,
            "dispatch_id": str(dispatch.dispatch_id),
            "alert_job_id": str(dispatch.alert_job_id),
            "correlation_id": str(dispatch.correlation_id),
        },
        store=store,
        support=Support(),
        logger=logging.getLogger(__name__),
        providers={"email": Provider()},
    )
    if late:
        current[0] += timedelta(days=1)
        store.maintain(dispatch.dispatch_id, dispatch.alert_job_id, dispatch.correlation_id)
    assert (
        store.reconcile_delivery(sent[0].attempt_id, "known-reference", "delivered", current[0])
        == "applied"
    )
    store.maintain(dispatch.dispatch_id, dispatch.alert_job_id, dispatch.correlation_id)
    assert (
        store.reconcile_delivery(sent[0].attempt_id, "known-reference", "accepted", current[0])
        == "ignored"
    )
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_recipients)).one().status == "delivered"
        assert connection.execute(select(alert_jobs)).one().status == (
            "expired" if late else "completed"
        )
        assert (
            connection.execute(
                select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch.dispatch_id)
            )
            .one()
            .status
            == "stopped"
        )


def test_delivery_lifecycle_uses_only_approved_worker_grants(migrated_engine):
    import re
    from pathlib import Path

    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from quakestrike.application.alert_delivery import SubmissionResult

    dispatch, _ = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)
    provisioning = (
        Path(__file__).resolve().parents[3] / "database/initialization/provision-roles.sh"
    ).read_text(encoding="utf-8")
    worker_sql = re.search(
        r"<<'SQL'\n(.*?)\nSQL", provisioning.split("  grant-worker)", 1)[1], re.S
    ).group(1)

    class Provider:
        def submit(self, request):
            return SubmissionResult("accepted", reference="restricted-reference")

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE "
                    "rolname = 'quakestrike_worker') THEN CREATE ROLE quakestrike_worker "
                    "NOLOGIN; END IF; END $$; GRANT USAGE ON SCHEMA public "
                    "TO quakestrike_worker;"
                )
            )
            connection.execute(text(worker_sql))
            connection.execute(text("SET LOCAL ROLE quakestrike_worker"))
            store = SqlAlchemyAlertStore(sessionmaker(bind=connection), clock=lambda: NOW)
            assert (
                handle_alert_command(
                    {
                        "message_version": 1,
                        "dispatch_id": str(dispatch.dispatch_id),
                        "alert_job_id": str(dispatch.alert_job_id),
                        "correlation_id": str(dispatch.correlation_id),
                    },
                    store=store,
                    support=Support(),
                    logger=logging.getLogger(__name__),
                    providers={"email": Provider()},
                )
                == "delivering"
            )
        finally:
            transaction.rollback()


def test_resolution_runtime_budget_commits_partial_page_and_resumes_idempotently(
    migrated_engine, monkeypatch
):
    from datetime import timedelta

    import quakestrike.alert_worker.worker as worker
    from quakestrike.application.alert_delivery import SubmissionResult
    from quakestrike.infrastructure.database.dispatch import SqlAlchemyDispatchStore
    from quakestrike.infrastructure.database.tables import alert_recipients

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine)
    account(migrated_engine, mobile_number="+639171234568")
    elapsed, wall, lookups, sent = [0], [NOW], [], []
    monkeypatch.setattr(worker, "monotonic", lambda: elapsed[0], raising=False)

    class SlowSupport:
        def supported(self, phone):
            lookups.append(phone)
            elapsed[0] = 241
            return True

    class Provider:
        def submit(self, request):
            sent.append(request)
            return SubmissionResult("accepted", reference=str(request.attempt_id))

    payload = {
        "message_version": 1,
        "dispatch_id": str(dispatch.dispatch_id),
        "alert_job_id": str(dispatch.alert_job_id),
        "correlation_id": str(dispatch.correlation_id),
    }
    store = SqlAlchemyAlertStore(sessions, clock=lambda: wall[0])
    handle_alert_command(
        payload,
        store=store,
        support=SlowSupport(),
        logger=logging.getLogger(__name__),
        providers={"email": Provider(), "sms": Provider()},
    )
    assert len(lookups) == 1
    assert sent == []
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(select(alert_jobs)).one().recipient_resolution_completed_at is None
        )
        assert len(connection.execute(select(alert_recipients)).all()) == 2
    elapsed[0], wall[0] = 0, NOW + timedelta(seconds=60)
    publisher = SqlAlchemyDispatchStore(sessions, clock=lambda: wall[0], alerts_enabled=True)
    claims = publisher.claim_due(10)
    assert len(claims) == 1
    publisher.mark_enqueued(claims[0])
    handle_alert_command(
        payload,
        store=store,
        support=Support(),
        logger=logging.getLogger(__name__),
        providers={"email": Provider(), "sms": Provider()},
    )
    assert len(sent) == 4
    with migrated_engine.connect() as connection:
        assert len(connection.execute(select(alert_recipients)).all()) == 4
        assert (
            connection.execute(select(alert_jobs)).one().recipient_resolution_completed_at
            is not None
        )


def test_repeated_slow_successful_resolution_makes_durable_progress(migrated_engine, monkeypatch):
    from datetime import timedelta

    import quakestrike.alert_worker.worker as worker
    from quakestrike.application.alert_delivery import SubmissionResult
    from quakestrike.infrastructure.database.dispatch import SqlAlchemyDispatchStore
    from quakestrike.infrastructure.database.tables import alert_recipients

    dispatch, sessions = queued(migrated_engine)
    for digit in range(3):
        account(migrated_engine, mobile_number=f"+63917123456{digit}")
    elapsed, wall, calls = [0], [NOW], []
    monkeypatch.setattr(worker, "monotonic", lambda: elapsed[0], raising=False)

    class SlowSupport:
        def supported(self, phone):
            calls.append(phone)
            elapsed[0] = 241
            return True

    class Provider:
        def submit(self, request):
            return SubmissionResult("accepted", reference=str(request.attempt_id))

    payload = {
        "message_version": 1,
        "dispatch_id": str(dispatch.dispatch_id),
        "alert_job_id": str(dispatch.alert_job_id),
        "correlation_id": str(dispatch.correlation_id),
    }
    store = SqlAlchemyAlertStore(sessions, clock=lambda: wall[0])
    for iteration in range(3):
        elapsed[0] = 0
        wall[0] = NOW + timedelta(seconds=60 * iteration)
        if iteration:
            dispatcher = SqlAlchemyDispatchStore(
                sessions, clock=lambda: wall[0], alerts_enabled=True
            )
            claims = dispatcher.claim_due(10)
            assert len(claims) == 1
            dispatcher.mark_enqueued(claims[0])
        handle_alert_command(
            payload,
            store=store,
            support=SlowSupport(),
            logger=logging.getLogger(__name__),
            providers={"email": Provider(), "sms": Provider()},
        )
        with migrated_engine.connect() as connection:
            assert len(connection.execute(select(alert_recipients)).all()) == 2 * (iteration + 1)
    assert len(set(calls)) == 3


def test_status_poll_without_provider_time_preserves_honest_time_evidence(migrated_engine):
    from quakestrike.application.alert_delivery import SubmissionResult
    from quakestrike.infrastructure.database.tables import alert_recipients

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)
    sent = []

    class Provider:
        def submit(self, request):
            sent.append(request)
            return SubmissionResult("accepted", reference="timeless-reference")

    store = SqlAlchemyAlertStore(sessions, clock=lambda: NOW)
    handle_alert_command(
        {
            "message_version": 1,
            "dispatch_id": str(dispatch.dispatch_id),
            "alert_job_id": str(dispatch.alert_job_id),
            "correlation_id": str(dispatch.correlation_id),
        },
        store=store,
        support=Support(),
        logger=logging.getLogger(__name__),
        providers={"email": Provider()},
    )
    assert (
        store.reconcile_delivery(sent[0].attempt_id, "timeless-reference", "delivered", None)
        == "applied"
    )
    assert (
        store.reconcile_delivery(sent[0].attempt_id, "timeless-reference", "accepted", None)
        == "ignored"
    )
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_delivery_attempts)).one().provider_status_at is None
        assert connection.execute(select(alert_recipients)).one().delivered_at == NOW


def test_concurrent_duplicate_command_does_not_start_second_call(migrated_engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from quakestrike.application.alert_delivery import SubmissionResult

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)
    entered, release, sent = Event(), Event(), []

    class Provider:
        def submit(self, request):
            sent.append(request)
            entered.set()
            assert release.wait(5)
            return SubmissionResult("accepted", reference="concurrent-reference")

    payload = {
        "message_version": 1,
        "dispatch_id": str(dispatch.dispatch_id),
        "alert_job_id": str(dispatch.alert_job_id),
        "correlation_id": str(dispatch.correlation_id),
    }

    def execute():
        return handle_alert_command(
            payload,
            store=SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
            support=Support(),
            logger=logging.getLogger(__name__),
            providers={"email": Provider()},
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(execute)
        try:
            assert entered.wait(5)
            assert execute() == "busy"
        finally:
            release.set()
        assert first.result(timeout=5) == "delivering"
    assert len(sent) == 1


@pytest.mark.parametrize("delay,expected", [(300, "retry_wait"), (100000, "expired")])
def test_trusted_retry_timing_is_never_shortened_to_fit_expiry(migrated_engine, delay, expected):
    from datetime import timedelta

    from quakestrike.application.alert_delivery import SubmissionResult
    from quakestrike.infrastructure.database.tables import alert_recipients

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)

    class Provider:
        def submit(self, request):
            return SubmissionResult(
                "transient", error_code="provider_rate_limited", retry_after_seconds=delay
            )

    handle_alert_command(
        {
            "message_version": 1,
            "dispatch_id": str(dispatch.dispatch_id),
            "alert_job_id": str(dispatch.alert_job_id),
            "correlation_id": str(dispatch.correlation_id),
        },
        store=SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
        support=Support(),
        logger=logging.getLogger(__name__),
        providers={"email": Provider()},
    )
    with migrated_engine.connect() as connection:
        recipient = connection.execute(select(alert_recipients)).one()
        assert recipient.status == expected
        assert recipient.next_attempt_at == (
            NOW + timedelta(seconds=300) if expected == "retry_wait" else None
        )


def test_retry_selects_current_nearby_variant_and_preserves_previous_evidence(migrated_engine):
    from datetime import timedelta
    from decimal import Decimal

    from sqlalchemy import update

    from quakestrike.application.alert_delivery import SubmissionResult
    from quakestrike.infrastructure.database.dispatch import SqlAlchemyDispatchStore
    from quakestrike.infrastructure.database.tables import users

    dispatch, sessions = queued(migrated_engine)
    user_id = account(migrated_engine, email_enabled=False)
    current, sent = [NOW], []

    class Provider:
        def submit(self, request):
            sent.append(request)
            if len(sent) == 1:
                return SubmissionResult("transient", error_code="provider_rejected")
            return SubmissionResult("accepted", reference="nearby-reference")

    store = SqlAlchemyAlertStore(sessions, clock=lambda: current[0])
    payload = {
        "message_version": 1,
        "dispatch_id": str(dispatch.dispatch_id),
        "alert_job_id": str(dispatch.alert_job_id),
        "correlation_id": str(dispatch.correlation_id),
    }
    handle_alert_command(
        payload,
        store=store,
        support=Support(),
        logger=logging.getLogger(__name__),
        providers={"sms": Provider()},
    )
    with migrated_engine.begin() as connection:
        connection.execute(
            update(users)
            .where(users.c.user_id == user_id)
            .values(
                nearby_alerts_only=True,
                alert_location_latitude=Decimal("14.123456"),
                alert_location_longitude=Decimal("121.123456"),
                alert_trigger_distance_km=Decimal("50"),
            )
        )
    current[0] += timedelta(seconds=30)
    dispatcher = SqlAlchemyDispatchStore(sessions, clock=lambda: current[0], alerts_enabled=True)
    claim = dispatcher.claim_due(10)[0]
    dispatcher.mark_enqueued(claim)
    handle_alert_command(
        payload,
        store=store,
        support=Support(),
        logger=logging.getLogger(__name__),
        providers={"sms": Provider()},
    )
    assert len(sent) == 2
    with migrated_engine.connect() as connection:
        job = connection.execute(select(alert_jobs)).one()
        attempts = connection.execute(
            select(alert_delivery_attempts).order_by(alert_delivery_attempts.c.attempt_number)
        ).all()
        assert sent[0].body == job.message_snapshot and sent[1].body == job.nearby_message_snapshot
        assert [row.content_variant for row in attempts] == ["general", "nearby"]
        assert [row.eligibility_snapshot["nearby_alerts_only"] for row in attempts] == [False, True]


@pytest.mark.parametrize("outcome", ["accepted", "unknown"])
def test_expiry_during_post_retains_returned_evidence_and_stops_unsent_work(
    migrated_engine, outcome
):
    from datetime import timedelta

    from quakestrike.application.alert_delivery import SubmissionResult
    from quakestrike.infrastructure.database.tables import alert_recipients

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)
    account(migrated_engine, sms_enabled=False, mobile_number=None, mobile_verified_at=None)
    current, calls = [NOW], []

    class Provider:
        def submit(self, request):
            calls.append(request)
            current[0] += timedelta(days=1)
            return SubmissionResult(
                outcome,
                reference="expired-inflight-reference",
                evidence={"http_status": 201, "provider_code": 200},
            )

    assert (
        handle_alert_command(
            {
                "message_version": 1,
                "dispatch_id": str(dispatch.dispatch_id),
                "alert_job_id": str(dispatch.alert_job_id),
                "correlation_id": str(dispatch.correlation_id),
            },
            store=SqlAlchemyAlertStore(sessions, clock=lambda: current[0]),
            support=Support(),
            logger=logging.getLogger(__name__),
            providers={"email": Provider()},
        )
        == "expired"
    )
    assert len(calls) == 1
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_jobs)).one().status == "expired"
        assert {row.status for row in connection.execute(select(alert_recipients))} == {
            outcome,
            "expired",
        }
        attempt = connection.execute(select(alert_delivery_attempts)).one()
        assert attempt.provider_message_id == "expired-inflight-reference"
        assert attempt.provider_evidence_snapshot == {"http_status": 201, "provider_code": 200}
