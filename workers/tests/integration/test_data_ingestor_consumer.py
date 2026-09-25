from __future__ import annotations

import logging
import os
from datetime import timedelta
from multiprocessing import get_context
from threading import Event
from uuid import uuid4

import pytest
from celery.contrib.testing.worker import start_worker
from kombu import Connection
from redis import Redis
from sqlalchemy import func, insert, select

from quakestrike.application.dispatch import DurableDispatcher
from quakestrike.application.persistence import (
    EventRevisionRequest,
    EventTransactionRequest,
    RunDispatchRequest,
)
from quakestrike.application.reconciliation import ReconcileCurrentCatalog
from quakestrike.data_ingestor.worker import create_ingestor_app, handle_ingestion_command
from quakestrike.domain.features import INPUT_SCHEMA_VERSION, HistoryCoverage
from quakestrike.domain.source_rows import CatalogEvidence, CatalogParseResult, NormalizedSourceRow
from quakestrike.infrastructure.database.dispatch import SqlAlchemyDispatchStore
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.database.tables import (
    earthquake_event_revisions,
    earthquake_events,
    ingestion_runs,
    job_dispatches,
    model_releases,
    prediction_jobs,
    source_catalog_evidence,
)
from quakestrike.infrastructure.queues.celery_app import (
    DURABLE_INGESTION_TICK,
    INGESTION_QUEUE,
    INGESTION_TASK_NAME,
    PREDICTION_QUEUE,
    create_celery_app,
)
from quakestrike.infrastructure.queues.contracts import IngestionCommandV1
from quakestrike.infrastructure.queues.ingestion_publisher import CeleryIngestionPublisher
from quakestrike.infrastructure.queues.prediction_publisher import (
    PREDICTION_TASK_NAME,
    CeleryPredictionPublisher,
)
from quakestrike.infrastructure.settings import Settings
from quakestrike.scheduler.beat import DurableBeatScheduler, run_scheduled_ingestion_tick

pytestmark = pytest.mark.integration


class _VerifiedRelease:
    def is_verified(self, _release_id) -> bool:
        return True


class _Retriever:
    def __init__(self, row: NormalizedSourceRow, evidence: CatalogEvidence | None = None) -> None:
        self.row = row
        self.evidence = evidence

    def retrieve_current_catalog(self, *, heartbeat=None) -> CatalogParseResult:
        assert heartbeat is not None
        assert heartbeat()
        return CatalogParseResult((self.row,), (), evidence=self.evidence)


class _Reporter:
    def report(self, _diagnostic) -> None:
        pass


def test_valid_command_persists_one_completed_run_and_duplicate_is_a_no_op(
    migrated_engine,
) -> None:
    session_factory = create_session_factory(migrated_engine)
    store = SqlAlchemyIngestionTransactions(
        session_factory,
        model_release_verifier=_VerifiedRelease(),
    )
    request = RunDispatchRequest(
        run_id=uuid4(),
        dispatch_id=uuid4(),
        trigger_type="scheduled",
        correlation_id=uuid4(),
    )
    store.create_run_with_dispatch(request)
    with migrated_engine.connect() as connection:
        database_now = connection.scalar(select(func.now()))
    model_release_id = uuid4()
    bootstrap_run_id = uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(ingestion_runs).values(
                run_id=bootstrap_run_id,
                trigger_type="backfill",
                status="succeeded",
                started_at=database_now - timedelta(days=8),
                finished_at=database_now - timedelta(days=1),
                correlation_id=uuid4(),
                bootstrap_snapshot_sha256=uuid4().hex * 2,
            )
        )
        connection.execute(
            insert(model_releases).values(
                model_release_id=model_release_id,
                version_label="SEIS 1.0",
                artifact_manifest_uri="model-artifacts/seis-1.0/manifest.json",
                artifact_manifest_hash="a" * 64,
                input_schema_version=INPUT_SCHEMA_VERSION,
                output_schema_version="quakestrike.prediction-output.v1",
            )
        )
    store.process_event(
        EventTransactionRequest(
            event_id=uuid4(),
            ingestion_run_id=bootstrap_run_id,
            revision=EventRevisionRequest(
                event_revision_id=uuid4(),
                ingestion_run_id=bootstrap_run_id,
                source_bulletin_id="2026_0918_1100_B1",
                source_event_group_id="2026_0918_1100",
                source_url="https://earthquake.phivolcs.dost.gov.ph/2026_0918_1100_B1.html",
                source_time_precision="second",
                event_time=database_now - timedelta(hours=2),
                latitude=14,
                longitude=121,
                depth_km=10,
                magnitude=2,
                location_description="Prior test location",
            ),
        )
    )

    row = NormalizedSourceRow.from_catalog_values(
        occurred_at=database_now - timedelta(hours=1),
        latitude="14.00",
        longitude="121.00",
        depth_km="10",
        magnitude="4.2",
        location_description="Test location",
        source_bulletin_id="2026_0918_1200_B1",
        source_event_group_id="2026_0918_1200",
        source_url="https://earthquake.phivolcs.dost.gov.ph/2026_0918_1200_B1.html",
    )
    reconciler = ReconcileCurrentCatalog(
        store=store,
        retriever=_Retriever(
            row,
            CatalogEvidence(
                source_url="https://earthquake.phivolcs.dost.gov.ph/",
                sha256="a" * 64,
                retrieved_at=database_now,
                coverage_start=database_now - timedelta(days=8),
                coverage_end=database_now,
                accepted_rows=1,
            ),
        ),
        diagnostic_reporter=_Reporter(),
        model_release_id=model_release_id,
        now=lambda: database_now,
    )
    payload = IngestionCommandV1(
        dispatch_id=request.dispatch_id,
        run_id=request.run_id,
        correlation_id=request.correlation_id,
    ).to_message()

    first = handle_ingestion_command(
        payload,
        store=store,
        reconciler=reconciler,
        logger=logging.getLogger("test-data-ingestor"),
    )
    replay = handle_ingestion_command(
        payload,
        store=store,
        reconciler=reconciler,
        logger=logging.getLogger("test-data-ingestor"),
    )

    assert first == "succeeded"
    assert replay == "not_claimed"
    with migrated_engine.connect() as connection:
        run = connection.execute(
            select(ingestion_runs).where(ingestion_runs.c.run_id == request.run_id)
        ).one()
        assert run.status == "succeeded"
        assert run.attempt_count == 1
        assert run.events_found == 1
        assert run.events_inserted == 1
        assert (
            connection.scalar(
                select(source_catalog_evidence.c.catalog_sha256).where(
                    source_catalog_evidence.c.run_id == request.run_id
                )
            )
            == "a" * 64
        )
        assert connection.scalar(select(func.count()).select_from(earthquake_events)) == 2
        dispatches = connection.execute(
            select(job_dispatches).order_by(job_dispatches.c.dispatch_id)
        ).all()
        assert len(dispatches) == 2
        ingestion_dispatch = next(
            dispatch for dispatch in dispatches if dispatch.ingestion_run_id == request.run_id
        )
        prediction_dispatch = next(
            dispatch for dispatch in dispatches if dispatch.prediction_job_id is not None
        )
        assert ingestion_dispatch.dispatch_id == request.dispatch_id
        assert prediction_dispatch.prediction_job_id is not None
        revision = connection.execute(
            select(earthquake_event_revisions).where(
                earthquake_event_revisions.c.ingestion_run_id == request.run_id
            )
        ).one()
        assert revision.prediction_skip_reason is None
        prediction_job = connection.execute(select(prediction_jobs)).one()
        assert prediction_job.job_id == prediction_dispatch.prediction_job_id
        assert prediction_job.correlation_id == request.correlation_id


def test_beat_to_ingestor_to_prediction_queue_replays_safely(migrated_engine) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    redis_url = os.environ.get("TEST_REDIS_URL")
    if database_url is None or redis_url is None:
        pytest.skip("TEST_DATABASE_URL and TEST_REDIS_URL are required for this integration test.")

    redis_client = Redis.from_url(redis_url)
    redis_client.delete(INGESTION_QUEUE, PREDICTION_QUEUE)
    try:
        with migrated_engine.connect() as connection:
            database_now = connection.scalar(select(func.now()))

        model_release_id = uuid4()
        bootstrap_run_id = uuid4()
        with migrated_engine.begin() as connection:
            connection.execute(
                insert(ingestion_runs).values(
                    run_id=bootstrap_run_id,
                    trigger_type="backfill",
                    status="succeeded",
                    started_at=database_now - timedelta(days=8),
                    finished_at=database_now - timedelta(days=1),
                    correlation_id=uuid4(),
                    bootstrap_snapshot_sha256=uuid4().hex * 2,
                )
            )
            connection.execute(
                insert(model_releases).values(
                    model_release_id=model_release_id,
                    version_label="SEIS 1.0",
                    artifact_manifest_uri="model-artifacts/seis-1.0/manifest.json",
                    artifact_manifest_hash="a" * 64,
                    input_schema_version=INPUT_SCHEMA_VERSION,
                    output_schema_version="quakestrike.prediction-output.v1",
                )
            )

        session_factory = create_session_factory(migrated_engine)
        transactions = SqlAlchemyIngestionTransactions(
            session_factory,
            model_release_verifier=_VerifiedRelease(),
        )
        transactions.process_event(
            EventTransactionRequest(
                event_id=uuid4(),
                ingestion_run_id=bootstrap_run_id,
                revision=EventRevisionRequest(
                    event_revision_id=uuid4(),
                    ingestion_run_id=bootstrap_run_id,
                    source_bulletin_id="2026_0918_1100_B1",
                    source_event_group_id="2026_0918_1100",
                    source_url="https://earthquake.phivolcs.dost.gov.ph/2026_0918_1100_B1.html",
                    source_time_precision="second",
                    event_time=database_now - timedelta(hours=2),
                    latitude=14,
                    longitude=121,
                    depth_km=10,
                    magnitude=2,
                    location_description="Prior test location",
                ),
            )
        )

        row = NormalizedSourceRow.from_catalog_values(
            occurred_at=database_now - timedelta(hours=1),
            latitude="14.00",
            longitude="121.00",
            depth_km="10",
            magnitude="4.2",
            location_description="Test location",
            source_bulletin_id="2026_0918_1200_B1",
            source_event_group_id="2026_0918_1200",
            source_url="https://earthquake.phivolcs.dost.gov.ph/2026_0918_1200_B1.html",
        )
        reconciler = ReconcileCurrentCatalog(
            store=transactions,
            retriever=_Retriever(row),
            diagnostic_reporter=_Reporter(),
            model_release_id=model_release_id,
            history_coverage=HistoryCoverage(
                database_now - timedelta(days=8),
                database_now,
                True,
            ),
            now=lambda: database_now,
        )
        settings = Settings(
            _env_file=None,
            database_url=database_url,
            redis_url=redis_url,
            phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
            model_release_id=model_release_id,
        )
        app = create_celery_app(
            settings,
            ingestion_tick=lambda: run_scheduled_ingestion_tick(transactions),
        )
        scheduler = DurableBeatScheduler(app)
        entry = scheduler.schedule["durable-ingestion-tick"]
        assert entry.task == DURABLE_INGESTION_TICK
        scheduler.apply_entry(entry)

        with migrated_engine.connect() as connection:
            scheduled = connection.execute(
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
        assert scheduled.run_status == "pending"
        assert scheduled.dispatch_status == "pending"

        dispatcher = DurableDispatcher(
            SqlAlchemyDispatchStore(session_factory),
            {
                "ingestion": CeleryIngestionPublisher(app),
                "prediction": CeleryPredictionPublisher(app),
            },
            batch_size=10,
            clock=lambda: scheduled.next_dispatch_at,
        )
        published_ingestion = dispatcher.dispatch_due()
        assert published_ingestion.target_counts_for("ingestion").enqueued == 1

        with Connection(redis_url) as connection:
            queue = connection.SimpleQueue(INGESTION_QUEUE)
            message = queue.get(block=False)
            try:
                ingestion_payload = message.payload[0][0]
                assert message.headers["task"] == INGESTION_TASK_NAME
                assert message.delivery_info["routing_key"] == INGESTION_QUEUE
                assert ingestion_payload["dispatch_id"] == str(scheduled.dispatch_id)
                assert ingestion_payload["run_id"] == str(scheduled.run_id)
                assert ingestion_payload["correlation_id"] == str(scheduled.correlation_id)
                assert (
                    handle_ingestion_command(
                        ingestion_payload,
                        store=transactions,
                        reconciler=reconciler,
                        logger=logging.getLogger("test-data-ingestor"),
                    )
                    == "succeeded"
                )
            finally:
                message.ack()
                queue.close()

        with migrated_engine.connect() as connection:
            prediction_dispatch = connection.execute(
                select(job_dispatches).where(job_dispatches.c.prediction_job_id.is_not(None))
            ).one()
            prediction_job = connection.execute(
                select(prediction_jobs).where(
                    prediction_jobs.c.job_id == prediction_dispatch.prediction_job_id
                )
            ).one()

        prediction_dispatcher = DurableDispatcher(
            SqlAlchemyDispatchStore(session_factory),
            {
                "ingestion": CeleryIngestionPublisher(app),
                "prediction": CeleryPredictionPublisher(app),
            },
            batch_size=10,
            clock=lambda: prediction_dispatch.next_dispatch_at,
        )
        published_prediction = prediction_dispatcher.dispatch_due()
        assert published_prediction.target_counts_for("prediction").enqueued == 1

        with Connection(redis_url) as connection:
            queue = connection.SimpleQueue(PREDICTION_QUEUE)
            message = queue.get(block=False)
            try:
                assert message.headers["task"] == PREDICTION_TASK_NAME
                assert message.delivery_info["routing_key"] == PREDICTION_QUEUE
                prediction_payload = message.payload[0][0]
                assert prediction_payload["dispatch_id"] == str(prediction_dispatch.dispatch_id)
                assert prediction_payload["job_id"] == str(prediction_job.job_id)
                assert prediction_payload["correlation_id"] == str(prediction_job.correlation_id)
            finally:
                message.ack()
                queue.close()

        assert (
            handle_ingestion_command(
                ingestion_payload,
                store=transactions,
                reconciler=reconciler,
                logger=logging.getLogger("test-data-ingestor"),
            )
            == "not_claimed"
        )
        with migrated_engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(prediction_jobs)) == 1
            assert connection.scalar(select(func.count()).select_from(job_dispatches)) == 2
    finally:
        redis_client.delete(INGESTION_QUEUE, PREDICTION_QUEUE)
        redis_client.close()


def test_mismatched_command_ids_never_claim_the_run(migrated_engine) -> None:
    store = SqlAlchemyIngestionTransactions(
        create_session_factory(migrated_engine),
        model_release_verifier=_VerifiedRelease(),
    )
    request = RunDispatchRequest(
        run_id=uuid4(),
        dispatch_id=uuid4(),
        trigger_type="scheduled",
        correlation_id=uuid4(),
    )
    store.create_run_with_dispatch(request)

    result = handle_ingestion_command(
        IngestionCommandV1(
            dispatch_id=request.dispatch_id,
            run_id=request.run_id,
            correlation_id=uuid4(),
        ).to_message(),
        store=store,
        reconciler=pytest.fail,
        logger=logging.getLogger("test-data-ingestor"),
    )

    assert result == "rejected"
    with migrated_engine.connect() as connection:
        run = connection.execute(
            select(ingestion_runs).where(ingestion_runs.c.run_id == request.run_id)
        ).one()
    assert run.status == "pending"
    assert run.attempt_count == 0


def test_retryable_task_failure_is_redelivered_by_redis() -> None:
    context = get_context("spawn")
    results = context.Queue()
    process = context.Process(
        target=_run_redis_redelivery_check,
        args=(os.environ["TEST_DATABASE_URL"], os.environ["TEST_REDIS_URL"], results),
    )
    process.start()
    process.join(20)
    if process.is_alive():
        process.terminate()
        process.join(5)

    assert process.exitcode == 0
    assert results.get(timeout=1) == 2


def _run_redis_redelivery_check(database_url: str, redis_url: str, results) -> None:
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        redis_url=redis_url,
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id=uuid4(),
    )
    delivered = Event()
    attempts = 0

    def fail_once(_payload: object) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary database failure")
        delivered.set()
        return "succeeded"

    app = create_ingestor_app(settings, command_handler=fail_once)
    payload = IngestionCommandV1(
        dispatch_id=uuid4(),
        run_id=uuid4(),
        correlation_id=uuid4(),
    ).to_message()

    with start_worker(app, pool="solo", concurrency=1, perform_ping_check=False):
        app.send_task(INGESTION_TASK_NAME, args=[payload], queue=INGESTION_QUEUE)
        assert delivered.wait(10)

    results.put(attempts)
