from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, select, update

from quakestrike.alert_worker.worker import handle_alert_command
from quakestrike.application.alert_delivery import SubmissionResult, deliver_alert
from quakestrike.application.alerts import (
    AlertClaimLost,
    ResolveAlertRecipients,
    SmsSupportUnavailable,
)
from quakestrike.application.dispatch import AlertDispatch, DurableDispatcher
from quakestrike.infrastructure.database.alerts import SqlAlchemyAlertStore
from quakestrike.infrastructure.database.dispatch import SqlAlchemyDispatchStore
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.tables import (
    alert_delivery_attempts,
    alert_jobs,
    alert_recipients,
    job_dispatches,
    users,
)
from quakestrike.infrastructure.queues.alert_publisher import CeleryAlertPublisher

from .test_forecast_alert_evidence import completed_alert
from .test_prediction_worker import NOW

pytestmark = pytest.mark.integration


def account(engine, **extra):
    user_id = extra.get("user_id", uuid4())
    values = dict(
        user_id=user_id,
        clerk_user_id=str(user_id),
        display_name="Reader",
        email=f"{user_id}@example.invalid",
        email_verified_at=NOW,
        email_enabled=True,
        mobile_number="+639171234567",
        mobile_verified_at=NOW,
        sms_enabled=True,
        onboarding_completed_at=NOW,
        alert_trigger_magnitude=Decimal("4.2"),
    )
    values.update(extra)
    with engine.begin() as connection:
        connection.execute(insert(users).values(**values))
    return user_id


class Support:
    def supported(self, phone):
        return True


class Broker:
    def __init__(self):
        self.messages = []

    def send_task(self, name, **options):
        assert options["queue"] == "alert"
        self.messages.extend(options["args"])


def test_dispatch_to_resolution_records_two_independent_channels(migrated_engine):
    alert_id = completed_alert(migrated_engine)
    user_id = account(migrated_engine)
    broker = Broker()
    sessions = create_session_factory(migrated_engine)
    dispatcher = DurableDispatcher(
        SqlAlchemyDispatchStore(sessions, alerts_enabled=True),
        {
            "ingestion": CeleryAlertPublisher(broker),
            "prediction": CeleryAlertPublisher(broker),
            "alert": CeleryAlertPublisher(broker),
        },
        batch_size=10,
        clock=lambda: NOW,
    )
    result = dispatcher.dispatch_due()
    assert result.target_counts_for("alert").enqueued == 1
    store = SqlAlchemyAlertStore(sessions, clock=lambda: NOW)
    assert (
        handle_alert_command(
            broker.messages[0], store=store, support=Support(), logger=logging.getLogger(__name__)
        )
        == "resolved"
    )
    with migrated_engine.connect() as connection:
        rows = connection.execute(select(alert_recipients)).all()
        assert {(row.user_id, row.channel) for row in rows} == {
            (user_id, "email"),
            (user_id, "sms"),
        }
        assert all(row.eligibility_snapshot["observed_magnitude"] == 4.2 for row in rows)
        job = connection.execute(
            select(alert_jobs).where(alert_jobs.c.alert_job_id == alert_id)
        ).one()
        assert job.status == "delivering"
        assert job.recipient_resolution_completed_at is not None
        assert connection.execute(select(alert_delivery_attempts)).first() is None
    assert (
        handle_alert_command(
            broker.messages[0], store=store, support=Support(), logger=logging.getLogger(__name__)
        )
        == "already_resolved"
    )
    with migrated_engine.connect() as connection:
        assert len(connection.execute(select(alert_recipients)).all()) == 2


def queued(engine):
    completed_alert(engine)
    sessions = create_session_factory(engine)
    dispatches = SqlAlchemyDispatchStore(sessions, clock=lambda: NOW, alerts_enabled=True)
    claim = dispatches.claim_due(10, now=NOW)[0]
    dispatches.mark_enqueued(claim)
    return claim.dispatch, sessions


def resolve_direct(store, support, dispatch):
    return ResolveAlertRecipients(store, support).execute(
        dispatch.dispatch_id, dispatch.alert_job_id, dispatch.correlation_id
    )


def test_empty_roster_settles_job_and_dispatch_atomically(migrated_engine):
    dispatch, sessions = queued(migrated_engine)
    result = resolve_direct(SqlAlchemyAlertStore(sessions, clock=lambda: NOW), Support(), dispatch)
    assert result.status == "resolved"
    with migrated_engine.connect() as connection:
        job = connection.execute(select(alert_jobs)).one()
        assert job.status == "completed"
        assert job.completed_at == NOW
        assert job.recipient_resolution_completed_at == NOW
        assert job.worker_execution_id is None
        assert (
            connection.execute(
                select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch.dispatch_id)
            )
            .one()
            .status
            == "stopped"
        )


@pytest.mark.parametrize("page_size", [5, 100])
def test_slow_sms_exclusions_resume_to_later_email_and_sms(migrated_engine, page_size):
    dispatch, sessions = queued(migrated_engine)
    for number in range(1, 21):
        account(
            migrated_engine,
            user_id=UUID(int=number),
            email_enabled=number == 1,
            mobile_number=f"+63917{number:07d}",
        )
    later = account(migrated_engine, user_id=UUID(int=21))
    current, elapsed, calls = [NOW], [0], []

    class SlowSupport:
        def supported(self, phone):
            calls.append(phone)
            elapsed[0] += 11
            return phone == "+639171234567"

    def execute():
        store = SqlAlchemyAlertStore(
            sessions, clock=lambda: current[0], page_size=page_size, lease_seconds=60
        )
        return ResolveAlertRecipients(store, SlowSupport()).execute(
            dispatch.dispatch_id,
            dispatch.alert_job_id,
            dispatch.correlation_id,
            clock=lambda: elapsed[0],
            deadline=240,
        )

    first = execute()
    assert first.status == "incomplete"
    with migrated_engine.connect() as connection:
        original = connection.execute(select(alert_recipients)).all()
        skipped = [row for row in original if row.status == "skipped"]
        assert len(skipped) == 20
        assert all(row.last_error_code == "sms_sender_unsupported" for row in skipped)
        assert all(row.eligibility_snapshot["ordinary_sms_supported"] is False for row in skipped)
        assert [(row.user_id, row.channel) for row in original if row.status == "pending"] == [
            (UUID(int=1), "email")
        ]
        assert (
            connection.execute(select(alert_jobs)).one().recipient_resolution_completed_at is None
        )
    current[0] += timedelta(seconds=61)
    elapsed[0] = 0
    dispatcher = SqlAlchemyDispatchStore(sessions, clock=lambda: current[0], alerts_enabled=True)
    publishing = dispatcher.claim_due(10)[0]
    dispatcher.mark_enqueued(publishing)
    second = execute()
    assert second.status == "resolved"
    assert execute().status == "already_resolved"
    assert len(calls) == 21 and len(set(calls)) == 21
    with migrated_engine.connect() as connection:
        rows = connection.execute(select(alert_recipients)).all()
        assert len(rows) == 23
        assert {(row.user_id, row.channel) for row in rows if row.status == "pending"} == {
            (UUID(int=1), "email"),
            (later, "email"),
            (later, "sms"),
        }
        assert all(row in rows for row in original)
        job = connection.execute(select(alert_jobs)).one()
        assert job.status == "delivering"
        assert job.recipient_resolution_completed_at == current[0]
        assert connection.execute(select(alert_delivery_attempts)).first() is None

    submitted = []

    class Provider:
        def submit(self, request):
            submitted.append((request.channel, request.destination))
            return SubmissionResult("accepted", reference=str(request.attempt_id))

    assert (
        deliver_alert(
            second.claim,
            SqlAlchemyAlertStore(sessions, clock=lambda: current[0]),
            SlowSupport(),
            {"email": Provider(), "sms": Provider()},
            clock=lambda: elapsed[0],
            deadline=240,
            report=lambda *_: None,
        )
        == "delivering"
    )
    assert set(submitted) == {
        ("email", f"{UUID(int=1)}@example.invalid"),
        ("email", f"{later}@example.invalid"),
        ("sms", "+639171234567"),
    }
    with migrated_engine.connect() as connection:
        attempts = connection.execute(select(alert_delivery_attempts)).all()
        assert len(attempts) == 3 and all(row.status == "accepted" for row in attempts)


def test_only_unsupported_sms_settles_without_delivery_attempts(migrated_engine):
    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, email_enabled=False)

    class Unsupported:
        def supported(self, phone):
            return False

    result = resolve_direct(
        SqlAlchemyAlertStore(sessions, clock=lambda: NOW), Unsupported(), dispatch
    )
    assert result.status == "resolved" and result.claim is None
    with migrated_engine.connect() as connection:
        recipient = connection.execute(select(alert_recipients)).one()
        assert recipient.status == "skipped"
        assert recipient.last_error_code == "sms_sender_unsupported"
        job = connection.execute(select(alert_jobs)).one()
        assert job.status == "completed" and job.completed_at == NOW
        assert job.recipient_resolution_completed_at == NOW
        assert job.worker_execution_id is None and job.lease_expires_at is None
        assert (
            connection.execute(
                select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch.dispatch_id)
            )
            .one()
            .status
            == "stopped"
        )
        assert connection.execute(select(alert_delivery_attempts)).first() is None


def test_partial_sms_failure_recovery_preserves_email_and_fences_old_claim(migrated_engine):
    dispatch, sessions = queued(migrated_engine)
    user_id = account(migrated_engine)
    current = [NOW]
    store = SqlAlchemyAlertStore(sessions, clock=lambda: current[0], page_size=1, lease_seconds=60)

    class Unavailable:
        def supported(self, phone):
            raise SmsSupportUnavailable("private@example.invalid")

    first = resolve_direct(store, Unavailable(), dispatch)
    assert first.status == "incomplete"
    assert first.support_failures == ("sms_support_unavailable",)
    with migrated_engine.connect() as connection:
        rows = connection.execute(select(alert_recipients)).all()
        assert len(rows) == 1 and rows[0].channel == "email"
        original = rows[0].recipient_id, rows[0].eligibility_snapshot
        job = connection.execute(select(alert_jobs)).one()
        assert job.status == "resolving" and job.recipient_resolution_completed_at is None
    assert resolve_direct(store, Support(), dispatch).status == "busy"
    current[0] += timedelta(seconds=61)
    claims = SqlAlchemyDispatchStore(
        sessions, clock=lambda: current[0], alerts_enabled=True
    ).claim_due(10)
    assert len(claims) == 1 and isinstance(claims[0].dispatch, AlertDispatch)
    SqlAlchemyDispatchStore(sessions, clock=lambda: current[0], alerts_enabled=True).mark_enqueued(
        claims[0]
    )
    second = resolve_direct(store, Support(), dispatch)
    assert second.status == "resolved"
    with pytest.raises(AlertClaimLost):
        store.complete(first.claim)
    with migrated_engine.connect() as connection:
        rows = connection.execute(select(alert_recipients)).all()
        assert len(rows) == 2
        email = next(row for row in rows if row.channel == "email")
        assert (email.recipient_id, email.eligibility_snapshot) == original
        assert {row.user_id for row in rows} == {user_id}
        assert len({row.delivery_idempotency_key for row in rows}) == 2


def test_duplicate_destination_and_restart_keep_original_roster(migrated_engine):
    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)
    with migrated_engine.connect() as connection:
        email = connection.scalar(select(users.c.email))
    account(
        migrated_engine, mobile_number=None, mobile_verified_at=None, sms_enabled=False, email=email
    )
    store = SqlAlchemyAlertStore(sessions, clock=lambda: NOW, page_size=1)
    assert resolve_direct(store, Support(), dispatch).status == "resolved"
    assert resolve_direct(store, Support(), dispatch).status == "already_resolved"
    with migrated_engine.connect() as connection:
        assert len(connection.execute(select(alert_recipients)).all()) == 1


def test_expiry_and_incorrect_correlation_do_not_record_recipients(migrated_engine):
    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine)
    store = SqlAlchemyAlertStore(sessions, clock=lambda: NOW)
    assert store.claim(dispatch.dispatch_id, dispatch.alert_job_id, uuid4()) == "rejected"
    store = SqlAlchemyAlertStore(sessions, clock=lambda: NOW + timedelta(days=1))
    assert resolve_direct(store, Support(), dispatch).status == "expired"
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_recipients)).first() is None
        assert connection.execute(select(alert_jobs)).one().status == "expired"
        assert (
            connection.execute(
                select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch.dispatch_id)
            )
            .one()
            .status
            == "stopped"
        )


def test_live_claim_survives_publication_failure_and_recovers_after_expiry(migrated_engine):
    dispatch, sessions = queued(migrated_engine)
    with migrated_engine.begin() as connection:
        connection.execute(
            update(job_dispatches)
            .where(job_dispatches.c.dispatch_id == dispatch.dispatch_id)
            .values(status="retry_wait", next_dispatch_at=NOW, attempt_count=3)
        )
    dispatcher = SqlAlchemyDispatchStore(sessions, clock=lambda: NOW, alerts_enabled=True)
    publishing = dispatcher.claim_due(10)[0]
    root = SqlAlchemyAlertStore(sessions, clock=lambda: NOW, lease_seconds=60).claim(
        dispatch.dispatch_id, dispatch.alert_job_id, dispatch.correlation_id
    )
    assert root.token is not None
    assert dispatcher.mark_retry(publishing, RuntimeError("secret"), now=NOW) == "retry_wait"
    with migrated_engine.connect() as connection:
        row = connection.execute(
            select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch.dispatch_id)
        ).one()
        assert row.attempt_count == 0
        assert row.next_dispatch_at == NOW + timedelta(seconds=60)
    assert dispatcher.claim_due(10, now=NOW + timedelta(seconds=30)) == ()
    assert len(dispatcher.claim_due(10, now=NOW + timedelta(seconds=61))) == 1


def test_scan_upper_bound_excludes_accounts_created_during_support_lookup(migrated_engine):
    from uuid import UUID

    dispatch, sessions = queued(migrated_engine)
    original_id = UUID("00000000-0000-0000-0000-000000000001")
    account(migrated_engine, user_id=original_id)

    class NewAccountSupport:
        def supported(self, phone):
            account(
                migrated_engine,
                user_id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
                mobile_number=None,
                mobile_verified_at=None,
                sms_enabled=False,
            )
            return True

    result = resolve_direct(
        SqlAlchemyAlertStore(sessions, clock=lambda: NOW, page_size=1),
        NewAccountSupport(),
        dispatch,
    )
    assert result.status == "resolved"
    with migrated_engine.connect() as connection:
        rows = connection.execute(select(alert_recipients)).all()
        assert {(row.user_id, row.channel) for row in rows} == {
            (original_id, "email"),
            (original_id, "sms"),
        }


def test_lock_wait_cannot_authorize_a_write_after_root_lease_expires(migrated_engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    dispatch, sessions = queued(migrated_engine)
    store = SqlAlchemyAlertStore(sessions, clock=lambda: NOW, lease_seconds=60)
    root = store.claim(dispatch.dispatch_id, dispatch.alert_job_id, dispatch.correlation_id)
    current = [NOW]
    connection_requested = Event()

    def requested_session():
        connection_requested.set()
        return sessions()

    store.sessions = requested_session
    store.clock = lambda: current[0]
    with ThreadPoolExecutor(max_workers=1) as executor:
        with migrated_engine.begin() as connection:
            connection.execute(
                select(alert_jobs)
                .where(alert_jobs.c.alert_job_id == dispatch.alert_job_id)
                .with_for_update()
            ).one()
            blocked = executor.submit(store.record, root, [])
            assert connection_requested.wait(5)
            current[0] = NOW + timedelta(seconds=61)
        with pytest.raises(AlertClaimLost):
            blocked.result(timeout=5)


def test_dispatch_expiry_also_expires_unsent_recipients(migrated_engine):
    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)
    store = SqlAlchemyAlertStore(sessions, clock=lambda: NOW)
    assert resolve_direct(store, Support(), dispatch).status == "resolved"
    expired = NOW + timedelta(days=1)
    assert (
        SqlAlchemyDispatchStore(sessions, clock=lambda: expired, alerts_enabled=True).claim_due(10)
        == ()
    )
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_jobs)).one().status == "expired"
        assert (
            connection.execute(
                select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch.dispatch_id)
            )
            .one()
            .status
            == "stopped"
        )
        assert connection.execute(select(alert_recipients)).one().status == "expired"


def test_checkpoint_deadline_is_rechecked_before_commit(migrated_engine):
    dispatch, sessions = queued(migrated_engine)
    user_id = account(migrated_engine, sms_enabled=False)
    store = SqlAlchemyAlertStore(sessions, clock=lambda: NOW, lease_seconds=60)
    root = store.claim(dispatch.dispatch_id, dispatch.alert_job_id, dispatch.correlation_id)
    with migrated_engine.connect() as connection:
        email = connection.scalar(select(users.c.email).where(users.c.user_id == user_id))
    store.record(
        root,
        [
            {
                "user_id": user_id,
                "channel": "email",
                "destination": email,
                "evidence": {"channel": "email", "observed_magnitude": 4.2},
            }
        ],
    )
    times = iter((NOW, NOW + timedelta(seconds=61)))
    store.clock = lambda: next(times, NOW + timedelta(seconds=61))
    with pytest.raises(AlertClaimLost):
        store.complete(root)
    with migrated_engine.connect() as connection:
        job = connection.execute(select(alert_jobs)).one()
        assert job.status == "resolving"
        assert job.recipient_resolution_completed_at is None
        assert job.worker_execution_id == root.token


def test_known_equatorial_distance_uses_stored_radius_bounds_through_queue(migrated_engine):
    from quakestrike.infrastructure.models.deterministic_test import DeterministicTestModel
    from quakestrike.prediction_worker.worker import handle_prediction_command

    from .test_prediction_worker import seed
    from .test_prediction_worker import store as prediction_store

    command = seed(migrated_engine, latitude=Decimal("0"), longitude=Decimal("0"))
    assert (
        handle_prediction_command(
            command.to_message(),
            store=prediction_store(migrated_engine),
            model=DeterministicTestModel(),
            logger=logging.getLogger(__name__),
        )
        == "succeeded"
    )
    included = account(
        migrated_engine,
        sms_enabled=False,
        nearby_alerts_only=True,
        alert_location_latitude=Decimal("0"),
        alert_location_longitude=Decimal("1"),
        alert_trigger_distance_km=Decimal("111.196"),
    )
    account(
        migrated_engine,
        sms_enabled=False,
        mobile_number=None,
        mobile_verified_at=None,
        nearby_alerts_only=True,
        alert_location_latitude=Decimal("0"),
        alert_location_longitude=Decimal("1"),
        alert_trigger_distance_km=Decimal("111.195"),
    )
    broker = Broker()
    sessions = create_session_factory(migrated_engine)
    dispatcher = DurableDispatcher(
        SqlAlchemyDispatchStore(sessions, clock=lambda: NOW, alerts_enabled=True),
        {
            "ingestion": CeleryAlertPublisher(broker),
            "prediction": CeleryAlertPublisher(broker),
            "alert": CeleryAlertPublisher(broker),
        },
        batch_size=10,
        clock=lambda: NOW,
    )
    assert dispatcher.dispatch_due().target_counts_for("alert").enqueued == 1
    assert (
        handle_alert_command(
            broker.messages[0],
            store=SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
            support=Support(),
            logger=logging.getLogger(__name__),
        )
        == "resolved"
    )
    with migrated_engine.connect() as connection:
        rows = connection.execute(select(alert_recipients)).all()
        assert {(row.user_id, row.channel) for row in rows} == {(included, "email")}
        evidence = rows[0].eligibility_snapshot
        assert evidence["observed_magnitude"] == 4.2
        assert evidence["trigger_magnitude"] == 4.2
        assert evidence["distance_km"] == pytest.approx(111.1950802335329, abs=1e-10)


@pytest.mark.parametrize("supported", [True, False])
def test_resolution_succeeds_with_unchanged_restricted_worker_grants(migrated_engine, supported):
    import re
    from pathlib import Path

    from sqlalchemy import text
    from sqlalchemy.orm import Session

    dispatch, _ = queued(migrated_engine)
    user_id = account(migrated_engine)

    class SenderSupport:
        def supported(self, phone):
            return supported

    provisioning = (
        Path(__file__).resolve().parents[3] / "database/initialization/provision-roles.sh"
    ).read_text(encoding="utf-8")
    worker_sql = re.search(
        r"<<'SQL'\n(.*?)\nSQL", provisioning.split("  grant-worker)", 1)[1], re.S
    ).group(1)
    roles = text("SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = 'quakestrike_worker'")
    with migrated_engine.connect() as connection:
        original = connection.execute(roles).all()
        connection.rollback()
        transaction = connection.begin()
        try:
            connection.execute(
                text("""DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='quakestrike_worker') THEN
                    CREATE ROLE quakestrike_worker NOLOGIN;
                END IF;
                END $$;
                GRANT USAGE ON SCHEMA public TO quakestrike_worker;""")
            )
            connection.execute(text(worker_sql))
            connection.execute(text("SET LOCAL ROLE quakestrike_worker"))

            def sessions():
                return Session(bind=connection, join_transaction_mode="create_savepoint")

            result = resolve_direct(
                SqlAlchemyAlertStore(sessions, clock=lambda: NOW), SenderSupport(), dispatch
            )
            assert result.status == "resolved"
            rows = connection.execute(select(alert_recipients)).all()
            assert {(row.user_id, row.channel) for row in rows} == {
                (user_id, "email"),
                (user_id, "sms"),
            }
            assert next(row for row in rows if row.channel == "sms").status == (
                "pending" if supported else "skipped"
            )
            job = connection.execute(select(alert_jobs)).one()
            assert job.status == "delivering"
            assert job.recipient_resolution_completed_at == NOW
        finally:
            transaction.rollback()
        assert connection.execute(roles).all() == original
