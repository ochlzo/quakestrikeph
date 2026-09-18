from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from kombu import Connection
from redis import Redis
from sqlalchemy import select, update

from quakestrike.application.ingestion_dispatch import DurableIngestionDispatcher
from quakestrike.application.scheduling import ScheduleIngestionPoll
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.ingestion_dispatch import (
    SqlAlchemyIngestionDispatchStore,
)
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.database.tables import ingestion_runs, job_dispatches
from quakestrike.infrastructure.queues.celery_app import (
    DURABLE_INGESTION_TICK,
    INGESTION_QUEUE,
    INGESTION_TASK_NAME,
    create_celery_app,
)
from quakestrike.infrastructure.queues.ingestion_publisher import CeleryIngestionPublisher
from quakestrike.infrastructure.settings import Settings
from quakestrike.scheduler.beat import DurableBeatScheduler, run_scheduled_ingestion_tick

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)


class AllowAllReleaseVerifier:
    def is_verified(self, _release_id) -> bool:  # type: ignore[no-untyped-def]
        return True


def test_manual_poll_reuses_the_active_scheduled_run(migrated_engine) -> None:
    transactions = SqlAlchemyIngestionTransactions(
        create_session_factory(migrated_engine),
        model_release_verifier=AllowAllReleaseVerifier(),  # type: ignore[arg-type]
    )
    scheduled = run_scheduled_ingestion_tick(transactions, clock=lambda: NOW)
    manual = ScheduleIngestionPoll(transactions, trigger_type="manual", clock=lambda: NOW).execute()

    assert scheduled.created is True
    assert manual.created is False
    assert (manual.run_id, manual.dispatch_id) == (scheduled.run_id, scheduled.dispatch_id)
    with migrated_engine.connect() as connection:
        rows = connection.execute(select(ingestion_runs.c.trigger_type)).all()
        dispatch_count = connection.execute(select(job_dispatches.c.dispatch_id)).all()
    assert rows == [("scheduled",)]
    assert len(dispatch_count) == 1


def test_beat_to_postgres_to_real_redis_ingestion_command(migrated_engine) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    redis_url = os.environ.get("TEST_REDIS_URL")
    if database_url is None or redis_url is None:
        pytest.skip("TEST_DATABASE_URL and TEST_REDIS_URL are required for this integration test.")

    redis_client = Redis.from_url(redis_url)
    redis_client.delete(INGESTION_QUEUE)
    try:
        settings = Settings(
            _env_file=None,
            database_url=database_url,
            redis_url=redis_url,
            phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
            model_release_id="00000000-0000-0000-0000-000000000001",
        )
        transactions = SqlAlchemyIngestionTransactions(
            create_session_factory(migrated_engine),
            model_release_verifier=AllowAllReleaseVerifier(),  # type: ignore[arg-type]
        )
        app = create_celery_app(
            settings,
            ingestion_tick=lambda: run_scheduled_ingestion_tick(transactions, clock=lambda: NOW),
        )
        scheduler = DurableBeatScheduler(app)
        entry = scheduler.schedule["durable-ingestion-tick"]
        assert entry.task == DURABLE_INGESTION_TICK

        scheduler.apply_entry(entry)

        with migrated_engine.connect() as connection:
            persisted = connection.execute(
                select(
                    ingestion_runs.c.run_id,
                    ingestion_runs.c.correlation_id,
                    ingestion_runs.c.status.label("run_status"),
                    job_dispatches.c.dispatch_id,
                    job_dispatches.c.status.label("dispatch_status"),
                    job_dispatches.c.next_dispatch_at,
                ).join(
                    job_dispatches,
                    job_dispatches.c.ingestion_run_id == ingestion_runs.c.run_id,
                )
            ).one()
        assert persisted.run_status == "pending"
        assert persisted.dispatch_status == "pending"

        store = SqlAlchemyIngestionDispatchStore(create_session_factory(migrated_engine))
        result = DurableIngestionDispatcher(
            store,
            CeleryIngestionPublisher(app),
            batch_size=10,
            clock=lambda: persisted.next_dispatch_at,
        ).dispatch_due()

        assert result.claimed == 1
        assert result.enqueued == 1
        with migrated_engine.connect() as connection:
            dispatch = connection.execute(
                select(job_dispatches).where(job_dispatches.c.dispatch_id == persisted.dispatch_id)
            ).one()
        assert dispatch.status == "enqueued"

        with Connection(redis_url) as connection:
            queue = connection.SimpleQueue(INGESTION_QUEUE)
            message = queue.get(block=False)
            try:
                assert message.headers["task"] == INGESTION_TASK_NAME
                assert message.delivery_info["routing_key"] == INGESTION_QUEUE
                assert message.payload[0][0] == {
                    "message_version": 1,
                    "dispatch_id": str(persisted.dispatch_id),
                    "run_id": str(persisted.run_id),
                    "correlation_id": str(persisted.correlation_id),
                }
            finally:
                message.ack()
                queue.close()
    finally:
        redis_client.delete(INGESTION_QUEUE)
        redis_client.close()


def test_failed_publication_and_expired_processing_recover_through_real_redis(
    migrated_engine,
) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    redis_url = os.environ.get("TEST_REDIS_URL")
    if database_url is None or redis_url is None:
        pytest.skip("TEST_DATABASE_URL and TEST_REDIS_URL are required for this integration test.")

    redis_client = Redis.from_url(redis_url)
    redis_client.delete(INGESTION_QUEUE)
    try:
        settings = Settings(
            _env_file=None,
            database_url=database_url,
            redis_url=redis_url,
            phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
            model_release_id="00000000-0000-0000-0000-000000000001",
        )
        transactions = SqlAlchemyIngestionTransactions(
            create_session_factory(migrated_engine),
            model_release_verifier=AllowAllReleaseVerifier(),  # type: ignore[arg-type]
        )
        scheduled = run_scheduled_ingestion_tick(transactions, clock=lambda: NOW)
        store = SqlAlchemyIngestionDispatchStore(create_session_factory(migrated_engine))
        with migrated_engine.connect() as connection:
            first_attempt_at = connection.scalar(
                select(job_dispatches.c.next_dispatch_at).where(
                    job_dispatches.c.dispatch_id == scheduled.dispatch_id
                )
            )
        unavailable_settings = settings.model_copy(update={"redis_url": "redis://127.0.0.1:1/0"})
        unavailable_app = create_celery_app(unavailable_settings)
        unavailable_app.conf.update(
            broker_connection_timeout=0.1,
            broker_transport_options={
                "max_retries": 0,
                "socket_connect_timeout": 0.1,
                "socket_timeout": 0.1,
            },
        )

        failed = DurableIngestionDispatcher(
            store,
            CeleryIngestionPublisher(unavailable_app),
            batch_size=10,
            clock=lambda: first_attempt_at,
        ).dispatch_due()

        assert failed.claimed == 1
        assert failed.retry_wait == 1
        assert redis_client.llen(INGESTION_QUEUE) == 0
        with migrated_engine.connect() as connection:
            retry_at = connection.scalar(
                select(job_dispatches.c.next_dispatch_at).where(
                    job_dispatches.c.dispatch_id == scheduled.dispatch_id
                )
            )

        app = create_celery_app(settings)
        retried = DurableIngestionDispatcher(
            store,
            CeleryIngestionPublisher(app),
            batch_size=10,
            clock=lambda: retry_at,
        ).dispatch_due()

        assert retried.claimed == 1
        assert retried.enqueued == 1
        with Connection(redis_url) as connection:
            queue = connection.SimpleQueue(INGESTION_QUEUE)
            message = queue.get(block=False)
            try:
                assert message.headers["task"] == INGESTION_TASK_NAME
                assert message.payload[0][0]["dispatch_id"] == str(scheduled.dispatch_id)
                assert message.payload[0][0]["run_id"] == str(scheduled.run_id)
            finally:
                message.ack()
                queue.close()

        processing_lease_expired_at = retry_at + timedelta(minutes=16)
        with migrated_engine.begin() as connection:
            connection.execute(
                update(ingestion_runs)
                .where(ingestion_runs.c.run_id == scheduled.run_id)
                .values(
                    status="running",
                    started_at=retry_at,
                    lease_expires_at=processing_lease_expired_at - timedelta(seconds=1),
                    worker_execution_id=uuid4(),
                )
            )
        recovered = DurableIngestionDispatcher(
            store,
            CeleryIngestionPublisher(app),
            batch_size=10,
            clock=lambda: processing_lease_expired_at,
        ).dispatch_due()

        assert recovered.claimed == 1
        assert recovered.enqueued == 1
        with Connection(redis_url) as connection:
            queue = connection.SimpleQueue(INGESTION_QUEUE)
            message = queue.get(block=False)
            try:
                assert message.payload[0][0]["dispatch_id"] == str(scheduled.dispatch_id)
                assert message.payload[0][0]["run_id"] == str(scheduled.run_id)
            finally:
                message.ack()
                queue.close()
    finally:
        redis_client.delete(INGESTION_QUEUE)
        redis_client.close()
