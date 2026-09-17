from __future__ import annotations

import logging
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from quakestrike.application.persistence import RunDispatchRequest
from quakestrike.application.reconciliation import ReconcileCurrentCatalog
from quakestrike.data_ingestor.worker import handle_ingestion_command
from quakestrike.domain.source_rows import CatalogParseResult, NormalizedSourceRow
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.database.tables import (
    earthquake_event_revisions,
    earthquake_events,
    ingestion_runs,
    prediction_jobs,
)
from quakestrike.infrastructure.queues.contracts import IngestionCommandV1

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
        model_release_id=uuid4(),
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
        assert connection.scalar(select(func.count()).select_from(earthquake_events)) == 1
        revision = connection.execute(select(earthquake_event_revisions)).one()
        assert revision.prediction_skip_reason == "history_coverage_unavailable"
        assert connection.scalar(select(func.count()).select_from(prediction_jobs)) == 0


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
