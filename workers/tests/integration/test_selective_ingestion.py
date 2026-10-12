"""Scheduled polls reuse complete rows without event transactions or checkpoints."""

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, update

from quakestrike.application.persistence import RunCounters, RunDispatchRequest
from quakestrike.application.reconciliation import ReconcileSourceRows
from quakestrike.domain.source_rows import CatalogParseResult
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.database.tables import (
    earthquake_event_revisions,
    earthquake_events,
    ingestion_run_inputs,
    ingestion_runs,
)
from quakestrike.infrastructure.phivolcs.parser import parse_current_catalog, parse_detail_page

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures" / "phivolcs"
CATALOG_URL = "https://earthquake.phivolcs.dost.gov.ph/"


class _VerifiedRelease:
    def is_verified(self, _release_id) -> bool:
        return True


class _Reporter:
    def report(self, _diagnostic) -> None:
        pass


def _row():
    catalog = parse_current_catalog((FIXTURES / "current_catalog.html").read_bytes(), CATALOG_URL)
    detail = parse_detail_page((FIXTURES / "bulletin_detail.html").read_bytes())
    return catalog.accepted_rows[0].with_detail_enrichment(
        detail_occurred_at=detail.occurred_at,
        origin=detail.origin,
        diagnostics=detail.diagnostics,
    )


def _run(store, rows, *, event_reporter=None):
    request = RunDispatchRequest(uuid4(), uuid4(), "scheduled", uuid4())
    store.create_run_with_dispatch(request)
    clock = datetime.now(UTC)
    reconciler = ReconcileSourceRows(
        store=store,
        source_loader=lambda **_: CatalogParseResult(tuple(rows), ()),
        diagnostic_reporter=_Reporter(),
        model_release_id=uuid4(),
        now=lambda: clock,
        event_reporter=event_reporter,
    )
    return request.run_id, reconciler


def test_new_then_unchanged_changed_and_disappeared_rows(migrated_engine) -> None:
    store = SqlAlchemyIngestionTransactions(
        create_session_factory(migrated_engine), model_release_verifier=_VerifiedRelease()
    )
    row = _row()
    first_id, first = _run(store, (row,))
    assert first.execute(first_id).status == "succeeded"
    with migrated_engine.connect() as connection:
        event_id = connection.scalar(select(earthquake_events.c.event_id))
        assert connection.scalar(select(func.count()).select_from(ingestion_run_inputs)) == 0

    second_id, second = _run(store, (row,))
    assert second.execute(second_id).status == "succeeded"
    with migrated_engine.connect() as connection:
        second_run = connection.execute(
            select(ingestion_runs).where(ingestion_runs.c.run_id == second_id)
        ).one()
        assert (second_run.events_found, second_run.events_unchanged) == (1, 1)
        assert connection.scalar(select(func.count()).select_from(earthquake_event_revisions)) == 1
        assert connection.scalar(select(func.count()).select_from(ingestion_run_inputs)) == 0
        assert connection.scalar(select(earthquake_events.c.last_seen_run_id)) == second_id

    changed = replace(row, magnitude=row.magnitude + Decimal("0.1"))
    third_id, third = _run(store, (changed,))
    assert third.execute(third_id).status == "succeeded"
    with migrated_engine.connect() as connection:
        third_run = connection.execute(
            select(ingestion_runs).where(ingestion_runs.c.run_id == third_id)
        ).one()
        assert (third_run.events_found, third_run.events_revised) == (1, 1)
        assert connection.scalar(select(func.count()).select_from(ingestion_run_inputs)) == 0

    other = replace(
        row,
        source_bulletin_id="2026_0901_0100_B1",
        source_event_group_id="2026_0901_0100",
        source_url=CATALOG_URL + "2026_0901_0100_B1.html",
    )
    fourth_id, fourth = _run(store, (other,))
    assert fourth.execute(fourth_id).status == "succeeded"
    with migrated_engine.connect() as connection:
        assert (
            connection.scalar(
                select(earthquake_events.c.last_seen_run_id).where(
                    earthquake_events.c.event_id == event_id
                )
            )
            == third_id
        )


def test_retry_keeps_changed_row_out_of_pre_run_unchanged_set(migrated_engine) -> None:
    store = SqlAlchemyIngestionTransactions(
        create_session_factory(migrated_engine), model_release_verifier=_VerifiedRelease()
    )
    row = _row()
    first_id, first = _run(store, (row,))
    assert first.execute(first_id).status == "succeeded"
    changed = replace(row, magnitude=row.magnitude + Decimal("0.1"))

    def interrupt(_claim, _result):
        raise RuntimeError("simulated interruption after commit")

    retry_id, interrupted = _run(store, (changed,), event_reporter=interrupt)
    assert interrupted.execute(retry_id).status == "retry_wait"
    with migrated_engine.connect() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(ingestion_run_inputs)
                .where(ingestion_run_inputs.c.run_id == retry_id)
            )
            == 1
        )
        assert store.unchanged_live_event_ids(retry_id, (changed,)) == {}
    with migrated_engine.begin() as connection:
        connection.execute(
            update(ingestion_runs)
            .where(ingestion_runs.c.run_id == retry_id)
            .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    resumed = ReconcileSourceRows(
        store=store,
        source_loader=lambda **_: CatalogParseResult((changed,), ()),
        diagnostic_reporter=_Reporter(),
        model_release_id=uuid4(),
    )
    assert resumed.execute(retry_id).status == "succeeded"
    with migrated_engine.connect() as connection:
        run = connection.execute(
            select(ingestion_runs).where(ingestion_runs.c.run_id == retry_id)
        ).one()
        assert (run.events_found, run.events_revised, run.events_unchanged) == (1, 1, 0)
        assert connection.scalar(select(func.count()).select_from(ingestion_run_inputs)) == 0
        assert connection.scalar(select(func.count()).select_from(earthquake_event_revisions)) == 2


def test_failed_success_transaction_keeps_summary_and_checkpoints(migrated_engine) -> None:
    store = SqlAlchemyIngestionTransactions(
        create_session_factory(migrated_engine), model_release_verifier=_VerifiedRelease()
    )
    run_id, _reconciler = _run(store, ())
    now = datetime.now(UTC)
    token = uuid4()
    assert store.claim_run(run_id, token, now) is not None
    assert store.checkpoint_input(run_id, token, "rejected:1:INVALID_CATALOG_ROW", "rejected", None)

    def fail_delete(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("DELETE FROM ingestion_run_inputs"):
            raise RuntimeError("simulated checkpoint deletion failure")

    event.listen(migrated_engine, "before_cursor_execute", fail_delete)
    try:
        with pytest.raises(RuntimeError, match="simulated checkpoint deletion failure"):
            store.complete_run(run_id, token, now, RunCounters(1, 0, 0, 0, 1))
    finally:
        event.remove(migrated_engine, "before_cursor_execute", fail_delete)

    with migrated_engine.connect() as connection:
        run = connection.execute(
            select(ingestion_runs).where(ingestion_runs.c.run_id == run_id)
        ).one()
        assert run.status == "running"
        assert run.events_found == 0
        assert connection.scalar(select(func.count()).select_from(ingestion_run_inputs)) == 1


def test_worker_role_can_delete_successful_scheduled_checkpoints(migrated_engine) -> None:
    script = (
        Path(__file__).resolve().parents[3] / "database/initialization/provision-roles.sh"
    ).read_text(encoding="utf-8")
    grants = script.split("  grant-worker)", 1)[1].split("<<'SQL'\n", 1)[1].split("\nSQL", 1)[0]
    with migrated_engine.begin() as connection:
        connection.exec_driver_sql(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
            "'quakestrike_worker') THEN CREATE ROLE quakestrike_worker; END IF; END $$"
        )
        connection.exec_driver_sql("GRANT USAGE ON SCHEMA public TO quakestrike_worker")
        connection.exec_driver_sql("REVOKE DELETE ON ingestion_run_inputs FROM quakestrike_worker")
        for statement in grants.split(";"):
            if statement.strip():
                connection.exec_driver_sql(statement)

    store = SqlAlchemyIngestionTransactions(
        create_session_factory(migrated_engine), model_release_verifier=_VerifiedRelease()
    )
    run_id, _reconciler = _run(store, ())
    now, token = datetime.now(UTC), uuid4()
    assert store.claim_run(run_id, token, now) is not None
    assert store.checkpoint_input(run_id, token, "rejected:1:INVALID_CATALOG_ROW", "rejected", None)

    worker_engine = create_engine(os.environ["TEST_DATABASE_URL"])

    @event.listens_for(worker_engine, "connect")
    def use_worker_role(dbapi_connection, _connection_record):
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET ROLE quakestrike_worker")

    try:
        worker_store = SqlAlchemyIngestionTransactions(
            create_session_factory(worker_engine), model_release_verifier=_VerifiedRelease()
        )
        assert worker_store.complete_run(run_id, token, now, RunCounters(1, 0, 0, 0, 1))
    finally:
        worker_engine.dispose()

    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ingestion_run_inputs)) == 0
