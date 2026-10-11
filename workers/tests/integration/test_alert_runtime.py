from types import SimpleNamespace

import pytest
from sqlalchemy import select

from quakestrike.alert_worker.worker import create_alert_handler
from quakestrike.infrastructure.database.alerts import SqlAlchemyAlertStore
from quakestrike.infrastructure.database.tables import alert_delivery_attempts

from .test_alert_resolution import Support, account, queued
from .test_prediction_worker import NOW

pytestmark = pytest.mark.integration


def test_enabled_runtime_delivers_both_channels_and_disabled_runtime_sends_nothing(migrated_engine):
    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine)
    calls = []

    class Provider:
        def submit(self, request):
            with migrated_engine.connect() as connection:
                attempt = connection.execute(
                    select(alert_delivery_attempts).where(
                        alert_delivery_attempts.c.delivery_attempt_id == request.attempt_id
                    )
                ).one()
                assert attempt.status == "sending"
            calls.append(request.channel)
            return SimpleNamespace(status="accepted", reference=str(request.attempt_id))

    settings = SimpleNamespace(alert_resolution_enabled=True, alert_delivery_enabled=False)
    dependencies = {
        "store": SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
        "support": Support(),
        "providers": {"sms": Provider(), "email": Provider()},
    }
    with pytest.raises(ValueError, match="disabled"):
        create_alert_handler(settings, **dependencies)
    assert calls == []
    settings.alert_delivery_enabled = True
    handler = create_alert_handler(settings, **dependencies)
    assert (
        handler(
            {
                "message_version": 1,
                "dispatch_id": str(dispatch.dispatch_id),
                "alert_job_id": str(dispatch.alert_job_id),
                "correlation_id": str(dispatch.correlation_id),
            }
        )
        == "delivering"
    )
    assert sorted(calls) == ["email", "sms"]


def test_reconciliation_settles_email_only_callback_without_queue_redelivery(migrated_engine):
    import logging
    from datetime import timedelta

    from sqlalchemy import text

    from quakestrike.alert_worker.reconciliation import AlertReconciliation
    from quakestrike.alert_worker.worker import handle_alert_command
    from quakestrike.infrastructure.database.tables import alert_jobs, job_dispatches

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)

    class Email:
        def submit(self, request):
            return SimpleNamespace(status="accepted", reference="email-callback-reference")

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
        providers={"email": Email()},
        logger=logging.getLogger(__name__),
    )
    with migrated_engine.begin() as connection:
        attempt_id = connection.scalar(select(alert_delivery_attempts.c.delivery_attempt_id))
        connection.execute(
            text(
                "SELECT quakestrike_reconcile_brevo_delivery(:attempt, :reference, "
                "'delivered', :observed, NULL)"
            ),
            {"attempt": attempt_id, "reference": "email-callback-reference", "observed": NOW},
        )
        assert connection.execute(select(alert_jobs)).one().status == "delivering"

    class NoSms:
        def poll(self, reference):
            pytest.fail("An email-only roster must not poll SMS.")

    store = SqlAlchemyAlertStore(sessions, clock=lambda: NOW + timedelta(seconds=1))
    assert AlertReconciliation(store, NoSms()).execute(limit=1)["maintained"] == 1
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_jobs)).one().status == "completed"
        assert (
            connection.execute(
                select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch.dispatch_id)
            )
            .one()
            .status
            == "stopped"
        )


def test_alert_startup_capabilities_require_restricted_worker_role(migrated_engine):
    import re
    from pathlib import Path

    from sqlalchemy import text

    from quakestrike.infrastructure.alert_readiness import alert_capabilities

    provisioning = (
        Path(__file__).resolve().parents[3] / "infrastructure/postgres/provision-roles.sh"
    ).read_text(encoding="utf-8")
    worker_sql = re.search(
        r"<<'SQL'\n(.*?)\nSQL", provisioning.split("  grant-worker)", 1)[1], re.S
    ).group(1)
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            assert alert_capabilities(connection).ready is False
            connection.execute(
                text(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE "
                    "rolname = 'quakestrike_worker') THEN CREATE ROLE quakestrike_worker "
                    "NOLOGIN; END IF; END $$; GRANT USAGE ON SCHEMA public TO quakestrike_worker;"
                )
            )
            connection.execute(text(worker_sql))
            connection.execute(text("SET LOCAL ROLE quakestrike_worker"))
            assert alert_capabilities(connection).ready is True
        finally:
            transaction.rollback()


def test_runtime_recovers_retained_command_after_database_outage_and_rejects_old_content(
    migrated_engine,
):
    import traceback

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine)
    real_store = SqlAlchemyAlertStore(sessions, clock=lambda: NOW)
    available, calls = [False], []

    class RecoveringStore:
        def __getattr__(self, name):
            if not available[0]:
                raise RuntimeError("DETAIL destination=private@example.invalid password=private")
            return getattr(real_store, name)

    class Provider:
        def submit(self, request):
            calls.append(request.channel)
            return SimpleNamespace(status="accepted", reference=str(request.attempt_id))

    handler = create_alert_handler(
        SimpleNamespace(alert_resolution_enabled=True, alert_delivery_enabled=True),
        store=RecoveringStore(),
        support=Support(),
        providers={"sms": Provider(), "email": Provider()},
    )
    payload = {
        "message_version": 1,
        "dispatch_id": str(dispatch.dispatch_id),
        "alert_job_id": str(dispatch.alert_job_id),
        "correlation_id": str(dispatch.correlation_id),
    }
    assert handler({**payload, "message_snapshot": "obsolete earthquake-only text"}) == "rejected"
    with pytest.raises(RuntimeError) as failure:
        handler(payload)
    detail = "".join(traceback.format_exception(failure.value))
    assert "private@example.invalid" not in detail and "password=private" not in detail
    assert calls == []
    available[0] = True
    assert handler(payload) == "delivering"
    handler(payload)
    assert sorted(calls) == ["email", "sms"]
    with migrated_engine.connect() as connection:
        assert len(connection.execute(select(alert_delivery_attempts)).all()) == 2
