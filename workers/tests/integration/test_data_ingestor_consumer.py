from __future__ import annotations

import logging
import os
from datetime import timedelta
from multiprocessing import get_context
from threading import Event
from uuid import uuid4

import pytest
from celery.contrib.testing.worker import start_worker
from sqlalchemy import func, insert, select

from quakestrike.application.persistence import (
    EventRevisionRequest,
    EventTransactionRequest,
    RunDispatchRequest,
)
from quakestrike.application.reconciliation import ReconcileCurrentCatalog
from quakestrike.data_ingestor.worker import create_ingestor_app, handle_ingestion_command
from quakestrike.domain.features import INPUT_SCHEMA_VERSION, HistoryCoverage
from quakestrike.domain.source_rows import CatalogParseResult, NormalizedSourceRow
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.database.tables import (
    earthquake_event_revisions,
    earthquake_events,
    ingestion_runs,
    job_dispatches,
    model_releases,
    prediction_jobs,
)
from quakestrike.infrastructure.queues.celery_app import INGESTION_QUEUE, INGESTION_TASK_NAME
from quakestrike.infrastructure.queues.contracts import IngestionCommandV1
from quakestrike.infrastructure.settings import Settings

pytestmark = pytest.mark.integration


class _VerifiedRelease:
    def is_verified(self, _release_id) -> bool:
        return True


class _Retriever:
    def __init__(self, row: NormalizedSourceRow) -> None:
        self.row = row

    def retrieve_current_catalog(self, *, heartbeat=None) -> CatalogParseResult:
        assert heartbeat is not None
        assert heartbeat()
        return CatalogParseResult((self.row,), ())


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
        assert connection.scalar(select(func.count()).select_from(earthquake_events)) == 2
        dispatch = connection.execute(select(job_dispatches)).one()
        assert dispatch.prediction_job_id is not None
        revision = connection.execute(
            select(earthquake_event_revisions).where(
                earthquake_event_revisions.c.ingestion_run_id == request.run_id
            )
        ).one()
        assert revision.prediction_skip_reason is None
        assert connection.scalar(select(func.count()).select_from(prediction_jobs)) == 1


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
