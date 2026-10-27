import json
import logging
from html import escape

import pytest
from sqlalchemy import select

from quakestrike.alert_worker.worker import handle_alert_command
from quakestrike.infrastructure.database.alerts import SqlAlchemyAlertStore
from quakestrike.infrastructure.database.tables import (
    alert_delivery_attempts,
    alert_jobs,
    alert_recipients,
)
from quakestrike.infrastructure.email.brevo import BrevoEmailProvider

from .test_alert_resolution import Support, account, queued
from .test_prediction_worker import NOW

pytestmark = pytest.mark.integration


def test_forecast_to_email_records_single_recipient_acceptance_without_inbox_delivery(
    migrated_engine,
):
    dispatch, sessions = queued(migrated_engine)
    account(migrated_engine, sms_enabled=False)
    calls = []

    def post(url, **options):
        with migrated_engine.connect() as connection:
            attempt = connection.execute(select(alert_delivery_attempts)).one()
            job = connection.execute(select(alert_jobs)).one()
            recipient = connection.execute(select(alert_recipients)).one()
            assert attempt.status == "sending"
            assert url == "https://api.brevo.com/v3/smtp/email"
            assert options["timeout"] == (3, 8)
            assert options["allow_redirects"] is False
            assert options["stream"] is True
            assert options["json"]["sender"] == {
                "email": "alerts@example.invalid",
                "name": "Fixture",
            }
            assert options["json"]["to"] == [{"email": recipient.destination_snapshot}]
            assert options["json"]["textContent"] == job.email_body_snapshot
            assert options["json"]["subject"] == job.email_subject_snapshot
            assert options["json"]["htmlContent"] == (
                f"<html><body><pre>{escape(job.email_body_snapshot)}</pre></body></html>"
            )
            assert set(options["json"]) == {
                "sender",
                "to",
                "subject",
                "textContent",
                "htmlContent",
                "headers",
            }
            assert str(recipient.worker_execution_id) not in json.dumps(options)
            assert options["json"]["headers"] == {
                "X-Mailin-custom": f"quakestrike-attempt:{attempt.delivery_attempt_id}"
            }
        calls.append(options)

        class Response:
            status_code = 201

            def __init__(self):
                self.headers = {}

            def iter_content(self, size):
                yield json.dumps({"messageId": "<fixture-email@brevo>"}).encode()

            def close(self):
                pass

        return Response()

    payload = {
        "message_version": 1,
        "dispatch_id": str(dispatch.dispatch_id),
        "alert_job_id": str(dispatch.alert_job_id),
        "correlation_id": str(dispatch.correlation_id),
    }
    assert (
        handle_alert_command(
            payload,
            store=SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
            support=Support(),
            providers={
                "email": BrevoEmailProvider(
                    "TEST_ONLY", "alerts@example.invalid", "Fixture", request=post
                )
            },
            logger=logging.getLogger(__name__),
        )
        == "delivering"
    )
    with migrated_engine.connect() as connection:
        attempt = connection.execute(select(alert_delivery_attempts)).one()
        assert attempt.status == "accepted"
        assert attempt.provider_message_id == "fixture-email@brevo"
        assert attempt.provider_status_at is None
        assert attempt.provider_evidence_snapshot == {
            "http_status": 201,
            "operation": "email_submit",
        }
    assert len(calls) == 1
