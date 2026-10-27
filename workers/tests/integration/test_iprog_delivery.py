import json
import logging
from datetime import timedelta

import pytest
from sqlalchemy import select

from quakestrike.alert_worker.worker import handle_alert_command
from quakestrike.infrastructure.database.alerts import SqlAlchemyAlertStore
from quakestrike.infrastructure.database.tables import (
    alert_delivery_attempts,
    alert_jobs,
    alert_recipients,
    job_dispatches,
)
from quakestrike.infrastructure.sms.iprog import IprogAlertProvider

from .test_alert_resolution import Support, account, queued
from .test_prediction_worker import NOW

pytestmark = pytest.mark.integration


class Response:
    status_code = 200

    def __init__(self, body):
        self.body = body
        self.headers = {}

    def json(self):
        return self.body

    def iter_content(self, size):
        yield json.dumps(self.json()).encode()

    def close(self):
        pass


def test_forecast_sms_acceptance_then_restart_poll_atomically_delivers(migrated_engine):
    from quakestrike.application.sms_polling import poll_iprog_deliveries

    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, email_enabled=False)
    sent = []

    def post(url, **kwargs):
        with migrated_engine.connect() as connection:
            attempt = connection.execute(select(alert_delivery_attempts)).one()
            job = connection.execute(select(alert_jobs)).one()
            recipient = connection.execute(select(alert_recipients)).one()
            assert attempt.status == "sending"
            assert url == "https://www.iprogsms.com/api/v1/sms_messages"
            assert kwargs == {
                "json": {
                    "api_token": "secret",
                    "phone_number": recipient.destination_snapshot,
                    "message": job.message_snapshot,
                },
                "timeout": (3, 8),
                "allow_redirects": False,
                "stream": True,
            }
            assert str(recipient.worker_execution_id) not in json.dumps(kwargs)
        sent.append(kwargs["json"]["message"])
        return Response({"status": 200, "message_id": "iSms-known", "sms_rate": 3})

    payload = {
        "message_version": 1,
        "dispatch_id": str(dispatch.dispatch_id),
        "alert_job_id": str(dispatch.alert_job_id),
        "correlation_id": str(dispatch.correlation_id),
    }
    handle_alert_command(
        payload,
        store=SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
        support=Support(),
        providers={"sms": IprogAlertProvider("secret", post=post)},
        logger=logging.getLogger(__name__),
    )
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_recipients)).one().status == "accepted"
        attempt = connection.execute(select(alert_delivery_attempts)).one()
        assert attempt.status == "accepted"
        assert attempt.provider_message_id == "iSms-known"
        assert attempt.provider_evidence_snapshot["provider_code"] == 200
        assert attempt.provider_evidence_snapshot["http_status"] == 200
    observed = []

    def get(url, **kwargs):
        observed.append((url, kwargs))
        return Response(
            {
                "status": 200,
                "message_status": "completed",
                "sms_count": 3,
                "raw": "secret destination message",
            }
        )

    restarted = SqlAlchemyAlertStore(sessions, clock=lambda: NOW)
    result = poll_iprog_deliveries(restarted, IprogAlertProvider("secret", get=get))
    assert result.processed == 1
    assert observed[0][0] == "https://www.iprogsms.com/api/v1/sms_messages/status"
    assert observed[0][1]["params"] == {"api_token": "secret", "message_id": "iSms-known"}
    assert observed[0][1]["allow_redirects"] is False
    with migrated_engine.connect() as connection:
        attempt = connection.execute(select(alert_delivery_attempts)).one()
        recipient = connection.execute(select(alert_recipients)).one()
        assert (attempt.status, recipient.status) == ("delivered", "delivered")
        assert attempt.provider_status_at is None
        assert attempt.provider_evidence_snapshot["charging_units"] == 3
        assert attempt.provider_evidence_snapshot["provider_sms_count"] == 3
        assert "secret" not in str(attempt.provider_evidence_snapshot)
        assert recipient.delivered_at == NOW
        assert connection.execute(select(alert_jobs)).one().status == "completed"
        assert (
            connection.execute(
                select(job_dispatches).where(job_dispatches.c.alert_job_id == dispatch.alert_job_id)
            )
            .one()
            .status
            == "stopped"
        )
    assert poll_iprog_deliveries(restarted, IprogAlertProvider("secret", get=get)).processed == 0
    assert len(sent) == 1


def send_sms(engine, response, *, headers=None, support=None, count=1):
    dispatch, sessions = queued(engine)
    for index in range(count):
        account(engine, email_enabled=False, mobile_number=f"+63917123456{index}")
    sent = []

    def post(*args, **kwargs):
        sent.append(kwargs)
        reply = Response(
            response
            if response is not None
            else {"status": 200, "message_id": f"known-{len(sent)}"}
        )
        if headers is not None:
            reply.status_code = 429
            reply.headers = headers
        return reply

    payload = {
        "message_version": 1,
        "dispatch_id": str(dispatch.dispatch_id),
        "alert_job_id": str(dispatch.alert_job_id),
        "correlation_id": str(dispatch.correlation_id),
    }
    handle_alert_command(
        payload,
        store=SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
        support=support or Support(),
        providers={"sms": IprogAlertProvider("secret", post=post)},
        logger=logging.getLogger(__name__),
    )
    return dispatch, sessions, sent


def test_huge_trusted_retry_wait_expires_without_overflow_or_another_submission(migrated_engine):
    _, _, sent = send_sms(migrated_engine, {}, headers={"Retry-After": "9" * 90})
    with migrated_engine.connect() as connection:
        attempt = connection.execute(select(alert_delivery_attempts)).one()
        recipient = connection.execute(select(alert_recipients)).one()
        assert attempt.status == "failed"
        assert recipient.status == "expired"
        assert recipient.next_attempt_at is None
    assert len(sent) == 1


def test_fixed_pages_advance_past_pending_attempts_and_wrap_after_exhaustion(migrated_engine):
    from quakestrike.application.sms_polling import poll_iprog_deliveries

    _, sessions, _ = send_sms(migrated_engine, None, count=3)
    requested = []

    def get(*a, **k):
        requested.append(k["params"]["message_id"])
        return Response({"status": 200, "message_status": "pending"})

    provider = IprogAlertProvider("secret", get=get)
    cursor = None
    for _ in range(3):
        # Recreate the store on each invocation: only the optional cursor is operational state.
        page = poll_iprog_deliveries(
            SqlAlchemyAlertStore(sessions), provider, after=cursor, limit=1
        )
        assert page.processed == 1
        assert page.next_after is not None
        cursor = page.next_after
    assert len(set(requested)) == 3
    page = poll_iprog_deliveries(SqlAlchemyAlertStore(sessions), provider, after=cursor, limit=1)
    assert (page.processed, page.next_after) == (0, None)
    assert poll_iprog_deliveries(SqlAlchemyAlertStore(sessions), provider, limit=1).processed == 1
    assert requested[0] == requested[-1]


@pytest.mark.parametrize("reference", [None, "known"])
def test_unknown_recovery_only_polls_saved_references_and_keeps_late_delivery(
    migrated_engine, reference
):
    from quakestrike.application.sms_polling import poll_iprog_deliveries

    body = {"status": "success"}
    if reference:
        body["message_id"] = reference
    dispatch, sessions, sent = send_sms(migrated_engine, body)
    current = NOW + timedelta(days=2)
    store = SqlAlchemyAlertStore(sessions, clock=lambda: current)
    assert (
        store.maintain(dispatch.dispatch_id, dispatch.alert_job_id, dispatch.correlation_id)
        == "expired"
    )
    gets = []

    def get(*a, **k):
        gets.append(k)
        return Response({"status": 200, "message_status": "completed"})

    page = poll_iprog_deliveries(store, IprogAlertProvider("secret", get=get))
    assert page.processed == (1 if reference else 0)
    assert len(gets) == (1 if reference else 0)
    with migrated_engine.connect() as connection:
        attempt = connection.execute(select(alert_delivery_attempts)).one()
        recipient = connection.execute(select(alert_recipients)).one()
        assert attempt.status == recipient.status == ("delivered" if reference else "unknown")
        assert attempt.provider_status_at is None
        assert connection.execute(select(alert_jobs)).one().status == "expired"
        assert (
            connection.execute(
                select(job_dispatches).where(job_dispatches.c.alert_job_id == dispatch.alert_job_id)
            )
            .one()
            .status
            == "stopped"
        )
    assert len(sent) == 1


@pytest.mark.parametrize("status", ["failed", "mystery", [], {"secret": "raw"}])
def test_failed_and_malformed_poll_responses_never_authorize_resend(migrated_engine, status):
    from quakestrike.application.sms_polling import poll_iprog_deliveries

    _, sessions, sent = send_sms(migrated_engine, None)
    poll_iprog_deliveries(
        SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
        IprogAlertProvider(
            "secret", get=lambda *a, **k: Response({"status": 200, "message_status": status})
        ),
    )
    with migrated_engine.connect() as connection:
        attempt = connection.execute(select(alert_delivery_attempts)).one()
        recipient = connection.execute(select(alert_recipients)).one()
        expected = "failed" if status == "failed" else "accepted"
        assert attempt.status == recipient.status == expected
        assert recipient.next_attempt_at is None
    assert len(sent) == 1


def test_stale_inflight_poll_cannot_regress_delivered_state(migrated_engine):
    from quakestrike.application.sms_polling import poll_iprog_deliveries

    _, sessions, _ = send_sms(migrated_engine, None)
    store = SqlAlchemyAlertStore(sessions, clock=lambda: NOW)

    def get(*a, **k):
        with migrated_engine.connect() as connection:
            attempt = connection.execute(select(alert_delivery_attempts)).one()
        assert (
            store.reconcile_delivery(
                attempt.delivery_attempt_id, attempt.provider_message_id, "delivered", None
            )
            == "applied"
        )
        return Response({"status": 200, "message_status": "failed"})

    poll_iprog_deliveries(store, IprogAlertProvider("secret", get=get))
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_delivery_attempts)).one().status == "delivered"
        assert connection.execute(select(alert_recipients)).one().status == "delivered"


def test_pending_poll_retains_separate_credit_and_count_evidence(migrated_engine):
    from quakestrike.application.sms_polling import poll_iprog_deliveries

    _, sessions, _ = send_sms(migrated_engine, None)
    poll_iprog_deliveries(
        SqlAlchemyAlertStore(sessions),
        IprogAlertProvider(
            "secret",
            get=lambda *a, **k: Response(
                {"status": 200, "message_status": "pending", "sms_rate": 2.5, "sms_count": 3}
            ),
        ),
    )
    with migrated_engine.connect() as connection:
        attempt = connection.execute(select(alert_delivery_attempts)).one()
        assert attempt.status == "accepted"
        assert attempt.provider_evidence_snapshot["charging_units"] == 2.5
        assert attempt.provider_evidence_snapshot["provider_sms_count"] == 3


@pytest.mark.parametrize("network,smart", [("Smart/TNT", True), ("Unknown Network", False)])
def test_shared_sender_excludes_unsupported_and_unknown_without_post(
    migrated_engine, network, smart, caplog
):
    from quakestrike.infrastructure.sms.iprog import IprogSmsSupport

    def detect(url, **options):
        assert url == "https://www.iprogsms.com/api/v1/phone_numbers/detect"
        assert options["timeout"] == (3, 8)
        assert options["allow_redirects"] is False
        return Response({"status": "success", "data": {"network": network, "is_smart_tnt": smart}})

    support = IprogSmsSupport("secret", request=detect)
    with caplog.at_level(logging.INFO):
        _, _, sent = send_sms(migrated_engine, None, support=support)
    assert sent == []
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_delivery_attempts)).first() is None
        assert connection.execute(select(alert_jobs)).one().status == (
            "completed" if smart else "resolving"
        )
        recipients = connection.execute(select(alert_recipients)).all()
        if smart:
            assert len(recipients) == 1
            assert recipients[0].status == "skipped"
            assert recipients[0].last_error_code == "sms_sender_unsupported"
        else:
            assert recipients == []
    assert "secret" not in caplog.text
    assert "+63917123456" not in caplog.text
