"""Prediction-to-delivery verification through the actual Redis alert queue."""

import json
import logging
import os

import pytest
from kombu import Connection
from redis import Redis
from sqlalchemy import select, text

from quakestrike.alert_worker.worker import handle_alert_command
from quakestrike.application.alert_delivery import SubmissionResult
from quakestrike.application.dispatch import DurableDispatcher
from quakestrike.application.sms_polling import SmsOutcome, poll_iprog_deliveries
from quakestrike.infrastructure.database.alerts import SqlAlchemyAlertStore
from quakestrike.infrastructure.database.dispatch import SqlAlchemyDispatchStore
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.tables import (
    alert_delivery_attempts,
    alert_jobs,
    alert_recipients,
    forecasts,
    job_dispatches,
)
from quakestrike.infrastructure.logging.json_logging import JsonFormatter
from quakestrike.infrastructure.models.deterministic_test import DeterministicTestModel
from quakestrike.infrastructure.queues.alert_publisher import ALERT_TASK_NAME, CeleryAlertPublisher
from quakestrike.infrastructure.queues.celery_app import ALERT_QUEUE, create_celery_app
from quakestrike.infrastructure.queues.ingestion_publisher import CeleryIngestionPublisher
from quakestrike.infrastructure.queues.prediction_publisher import CeleryPredictionPublisher
from quakestrike.infrastructure.settings import Settings
from quakestrike.prediction_worker.worker import handle_prediction_command

from .test_alert_resolution import Support, account
from .test_prediction_worker import NOW, seed, store

pytestmark = pytest.mark.integration


def test_prediction_commits_alert_then_real_redis_delivery_submits_once(migrated_engine, caplog):
    database_url, redis_url = os.getenv("TEST_DATABASE_URL"), os.getenv("TEST_REDIS_URL")
    if not database_url or not redis_url:
        pytest.skip("TEST_DATABASE_URL and TEST_REDIS_URL are required.")
    command = seed(migrated_engine)
    assert (
        handle_prediction_command(
            command.to_message(),
            store=store(migrated_engine),
            model=DeterministicTestModel(),
            logger=logging.getLogger(__name__),
        )
        == "succeeded"
    )
    user_id = account(migrated_engine)
    with migrated_engine.connect() as connection:
        forecast = connection.execute(select(forecasts)).one()
        job = connection.execute(select(alert_jobs)).one()
        dispatch = connection.execute(
            select(job_dispatches).where(
                job_dispatches.c.alert_job_id == job.alert_job_id,
            )
        ).one()
    assert job.forecast_id == forecast.forecast_id
    assert job.expires_at == forecast.window_end
    assert dispatch.status == "pending"

    settings = Settings(
        _env_file=None,
        database_url=database_url,
        redis_url=redis_url,
        phivolcs_catalog_url="https://example.invalid/catalog",
        model_release_id="00000000-0000-0000-0000-000000000001",
    )
    app, redis_client = create_celery_app(settings), Redis.from_url(redis_url)
    sessions = create_session_factory(migrated_engine)
    requests = []

    class Provider:
        def submit(self, request):
            with migrated_engine.connect() as connection:
                attempt = connection.execute(
                    select(alert_delivery_attempts).where(
                        alert_delivery_attempts.c.delivery_attempt_id == request.attempt_id,
                    )
                ).one()
                assert attempt.status == "sending"
            requests.append(request)
            return SubmissionResult(
                "accepted",
                reference=f"fixture-{request.channel}",
                evidence={"http_status": 201, "raw_payload": "PRIVATE_PROVIDER_PAYLOAD"},
            )

    alert_store = SqlAlchemyAlertStore(sessions, clock=lambda: NOW)
    providers = {"email": Provider(), "sms": Provider()}
    redis_client.delete(ALERT_QUEUE)
    caplog.set_level(logging.INFO, logger=__name__)
    try:
        result = DurableDispatcher(
            SqlAlchemyDispatchStore(sessions, alerts_enabled=True, clock=lambda: NOW),
            {
                "ingestion": CeleryIngestionPublisher(app),
                "prediction": CeleryPredictionPublisher(app),
                "alert": CeleryAlertPublisher(app),
            },
            batch_size=10,
            clock=lambda: NOW,
        ).dispatch_due()
        assert result.target_counts_for("alert").enqueued == 1
        with Connection(redis_url) as connection:
            queue = connection.SimpleQueue(ALERT_QUEUE)
            try:
                message = queue.get(block=False)
                try:
                    assert message.headers["task"] == ALERT_TASK_NAME
                    assert message.delivery_info["routing_key"] == ALERT_QUEUE
                    payload = message.payload[0][0]
                    assert payload == {
                        "message_version": 1,
                        "dispatch_id": str(dispatch.dispatch_id),
                        "alert_job_id": str(job.alert_job_id),
                        "correlation_id": str(job.correlation_id),
                    }
                    assert (
                        handle_alert_command(
                            payload,
                            store=alert_store,
                            support=Support(),
                            providers=providers,
                            logger=logging.getLogger(__name__),
                        )
                        == "delivering"
                    )
                    handle_alert_command(
                        payload,
                        store=alert_store,
                        support=Support(),
                        providers=providers,
                        logger=logging.getLogger(__name__),
                    )
                finally:
                    message.ack()
            finally:
                queue.close()
        assert len(requests) == 2
        assert {request.channel for request in requests} == {"email", "sms"}
        assert (
            next(request for request in requests if request.channel == "sms").body
            == job.message_snapshot
        )
        email = next(request for request in requests if request.channel == "email")
        assert (email.body, email.subject) == (job.email_body_snapshot, job.email_subject_snapshot)
        with migrated_engine.connect() as connection:
            recipients = connection.execute(select(alert_recipients)).all()
            attempts = connection.execute(select(alert_delivery_attempts)).all()
        assert {(row.user_id, row.channel, row.status) for row in recipients} == {
            (user_id, "email", "accepted"),
            (user_id, "sms", "accepted"),
        }
        assert len(attempts) == 2
        assert {row.provider_message_id for row in attempts} == {"fixture-email", "fixture-sms"}
        assert all(row.provider_status_at is None for row in attempts)
        assert all(row.provider_evidence_snapshot == {"http_status": 201} for row in attempts)
        with migrated_engine.connect() as connection:
            resolved = connection.execute(select(alert_jobs)).one()
            assert resolved.status == "delivering"
            assert resolved.recipient_resolution_completed_at is not None
        with migrated_engine.begin() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT quakestrike_reconcile_brevo_delivery(:attempt, "
                        "'fixture-email', 'delivered', :observed, NULL)"
                    ),
                    {"attempt": email.attempt_id, "observed": NOW},
                )
                == "applied"
            )

        class Sms:
            def poll(self, reference):
                assert reference == "fixture-sms"
                return SmsOutcome("delivered")

        assert poll_iprog_deliveries(alert_store, Sms()).processed == 1
        with migrated_engine.connect() as connection:
            assert {row.status for row in connection.execute(select(alert_recipients))} == {
                "delivered"
            }
            assert {row.status for row in connection.execute(select(alert_delivery_attempts))} == {
                "delivered"
            }
            assert connection.execute(select(alert_jobs)).one().status == "completed"
            assert (
                connection.execute(
                    select(job_dispatches).where(
                        job_dispatches.c.dispatch_id == dispatch.dispatch_id
                    )
                )
                .one()
                .status
                == "stopped"
            )
        assert (
            handle_alert_command(
                payload,
                store=alert_store,
                support=Support(),
                providers=providers,
                logger=logging.getLogger(__name__),
            )
            == "rejected"
        )
        assert len(requests) == 2
        with migrated_engine.connect() as connection:
            assert connection.execute(select(alert_jobs)).one().status == "completed"
            assert len(connection.execute(select(alert_delivery_attempts)).all()) == 2
            assert {row.status for row in connection.execute(select(alert_recipients))} == {
                "delivered"
            }
        logs = "\n".join(
            JsonFormatter("alert-verification").format(record) for record in caplog.records
        )
        for private in [
            "PRIVATE_PROVIDER_PAYLOAD",
            *(request.destination for request in requests),
            *(request.body for request in requests),
            *(str(request.token) for request in requests),
        ]:
            assert private not in logs
            assert json.dumps(private)[1:-1] not in logs
        assert redis_client.llen(ALERT_QUEUE) == 0
    finally:
        app.close()
        redis_client.delete(ALERT_QUEUE)
        redis_client.close()
