from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, update

from quakestrike.application.dispatch import (
    DispatchClaim,
    DispatchClaimLost,
    IngestionDispatch,
)
from quakestrike.infrastructure.database.dispatch import (
    SqlAlchemyDispatchStore,
)
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.tables import ingestion_runs, job_dispatches

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)


def _seed_pending_dispatch(
    engine,
    *,
    next_dispatch_at: datetime = NOW,
    run_status: str = "pending",
    run_next_attempt_at: datetime | None = None,
    run_lease_expires_at: datetime | None = None,
):
    run_id = uuid4()
    dispatch_id = uuid4()
    correlation_id = uuid4()
    with engine.begin() as connection:
        run_values = {
            "run_id": run_id,
            "trigger_type": "scheduled",
            "status": run_status,
            "correlation_id": correlation_id,
        }
        if run_status == "succeeded":
            run_values.update(
                started_at=NOW - timedelta(minutes=1),
                finished_at=NOW,
            )
        elif run_status == "retry_wait":
            run_values["next_attempt_at"] = run_next_attempt_at or NOW
        elif run_status == "running":
            run_values.update(
                started_at=NOW - timedelta(minutes=1),
                lease_expires_at=run_lease_expires_at or NOW,
                worker_execution_id=uuid4(),
            )
        connection.execute(insert(ingestion_runs).values(**run_values))
        connection.execute(
            insert(job_dispatches).values(
                dispatch_id=dispatch_id,
                ingestion_run_id=run_id,
                next_dispatch_at=next_dispatch_at,
            )
        )
    return run_id, dispatch_id, correlation_id


def test_claim_commits_before_acceptance_and_fences_enqueue(migrated_engine) -> None:
    run_id, dispatch_id, correlation_id = _seed_pending_dispatch(migrated_engine)
    store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))

    claims = store.claim_due(10, now=NOW)

    assert len(claims) == 1
    claim = claims[0]
    assert claim.dispatch.dispatch_id == dispatch_id
    assert claim.dispatch.run_id == run_id
    assert claim.dispatch.correlation_id == correlation_id
    with migrated_engine.connect() as connection:
        row = connection.execute(
            select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch_id)
        ).one()
    assert row.status == "dispatching"
    assert row.attempt_count == 1
    assert row.next_dispatch_at is None
    assert row.lease_expires_at == NOW + timedelta(seconds=60)
    assert row.dispatch_token == claim.token

    assert store.claim_due(10, now=NOW) == ()

    store.mark_enqueued(claim)

    with migrated_engine.connect() as connection:
        row = connection.execute(
            select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch_id)
        ).one()
    assert row.status == "enqueued"
    assert row.last_dispatched_at is not None
    assert row.next_dispatch_at is None
    assert row.lease_expires_at is None
    assert row.dispatch_token is None


def test_claim_is_due_only_and_fences_terminal_runs(migrated_engine) -> None:
    due = _seed_pending_dispatch(
        migrated_engine,
        next_dispatch_at=NOW - timedelta(minutes=1),
    )
    terminal = _seed_pending_dispatch(
        migrated_engine,
        next_dispatch_at=NOW - timedelta(minutes=2),
        run_status="succeeded",
    )
    store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))

    claims = store.claim_due(10, now=NOW)

    assert [claim.dispatch.dispatch_id for claim in claims] == [due[1]]
    with migrated_engine.connect() as connection:
        terminal_row = connection.execute(
            select(job_dispatches).where(job_dispatches.c.dispatch_id == terminal[1])
        ).one()
    assert terminal_row.status == "stopped"
    assert terminal_row.last_error == "dispatch target terminal"


def test_claim_fences_a_processing_retry_until_its_run_is_due(migrated_engine) -> None:
    run_id, dispatch_id, _ = _seed_pending_dispatch(
        migrated_engine,
        run_status="retry_wait",
        run_next_attempt_at=NOW + timedelta(minutes=1),
    )
    store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))

    assert store.claim_due(10, now=NOW) == ()

    with migrated_engine.connect() as connection:
        run = connection.execute(
            select(ingestion_runs).where(ingestion_runs.c.run_id == run_id)
        ).one()
        dispatch = connection.execute(
            select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch_id)
        ).one()
    assert run.status == "retry_wait"
    assert dispatch.status == "pending"


@pytest.mark.parametrize(
    ("run_status", "run_next_attempt_at", "run_lease_expires_at"),
    [
        ("retry_wait", NOW - timedelta(seconds=1), None),
        ("running", None, NOW - timedelta(seconds=1)),
    ],
)
def test_enqueued_dispatch_is_recovered_when_processing_becomes_due(
    migrated_engine,
    run_status: str,
    run_next_attempt_at: datetime | None,
    run_lease_expires_at: datetime | None,
) -> None:
    run_id, dispatch_id, correlation_id = _seed_pending_dispatch(
        migrated_engine,
        run_status=run_status,
        run_next_attempt_at=run_next_attempt_at,
        run_lease_expires_at=run_lease_expires_at,
    )
    with migrated_engine.begin() as connection:
        connection.execute(
            update(job_dispatches)
            .where(job_dispatches.c.dispatch_id == dispatch_id)
            .values(
                status="enqueued",
                next_dispatch_at=None,
                last_dispatched_at=NOW - timedelta(minutes=1),
                attempt_count=1,
            )
        )
    store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))

    claim = store.claim_due(1, now=NOW)[0]

    assert claim.dispatch == IngestionDispatch(
        dispatch_id=dispatch_id,
        run_id=run_id,
        correlation_id=correlation_id,
    )
    with migrated_engine.connect() as connection:
        dispatch = connection.execute(
            select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch_id)
        ).one()
    assert dispatch.status == "dispatching"
    assert dispatch.attempt_count == 2


@pytest.mark.parametrize(
    ("run_status", "run_next_attempt_at", "run_lease_expires_at"),
    [
        ("retry_wait", NOW + timedelta(minutes=1), None),
        ("running", None, NOW + timedelta(minutes=1)),
    ],
)
def test_enqueued_dispatch_stays_fenced_while_processing_is_not_due(
    migrated_engine,
    run_status: str,
    run_next_attempt_at: datetime | None,
    run_lease_expires_at: datetime | None,
) -> None:
    _, dispatch_id, _ = _seed_pending_dispatch(
        migrated_engine,
        run_status=run_status,
        run_next_attempt_at=run_next_attempt_at,
        run_lease_expires_at=run_lease_expires_at,
    )
    with migrated_engine.begin() as connection:
        connection.execute(
            update(job_dispatches)
            .where(job_dispatches.c.dispatch_id == dispatch_id)
            .values(
                status="enqueued",
                next_dispatch_at=None,
                last_dispatched_at=NOW - timedelta(minutes=1),
                attempt_count=1,
            )
        )
    store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))

    assert store.claim_due(1, now=NOW) == ()


def test_expired_submission_claim_is_not_republished_for_a_terminal_run(
    migrated_engine,
) -> None:
    run_id, dispatch_id, _ = _seed_pending_dispatch(migrated_engine, run_status="succeeded")
    old_token = uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            update(job_dispatches)
            .where(job_dispatches.c.dispatch_id == dispatch_id)
            .values(
                status="dispatching",
                next_dispatch_at=None,
                lease_expires_at=NOW - timedelta(seconds=1),
                dispatch_token=old_token,
                attempt_count=1,
            )
        )
    store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))

    assert store.claim_due(10, now=NOW) == ()

    with migrated_engine.connect() as connection:
        run = connection.execute(
            select(ingestion_runs).where(ingestion_runs.c.run_id == run_id)
        ).one()
        dispatch = connection.execute(
            select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch_id)
        ).one()
    assert run.status == "succeeded"
    assert dispatch.status == "stopped"
    assert dispatch.last_error == "dispatch target terminal"


def test_exhaustion_does_not_fail_a_live_processing_lease(migrated_engine) -> None:
    run_id, dispatch_id, _ = _seed_pending_dispatch(
        migrated_engine,
        run_status="running",
        run_lease_expires_at=NOW + timedelta(minutes=1),
    )
    old_token = uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            update(job_dispatches)
            .where(job_dispatches.c.dispatch_id == dispatch_id)
            .values(
                status="dispatching",
                next_dispatch_at=None,
                lease_expires_at=NOW - timedelta(seconds=1),
                dispatch_token=old_token,
                attempt_count=4,
            )
        )
    store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))

    assert store.claim_due(10, now=NOW) == ()

    with migrated_engine.connect() as connection:
        run = connection.execute(
            select(ingestion_runs).where(ingestion_runs.c.run_id == run_id)
        ).one()
    assert run.status == "running"
    assert run.lease_expires_at == NOW + timedelta(minutes=1)


def test_retry_delays_stop_exhausted_dispatch_without_replacing_ids(migrated_engine) -> None:
    run_id, dispatch_id, correlation_id = _seed_pending_dispatch(migrated_engine)
    store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))
    original = (run_id, dispatch_id, correlation_id)
    claim = store.claim_due(1, now=NOW)[0]

    for delay_seconds in (30, 120, 600):
        assert store.mark_retry(claim, RuntimeError("Redis unavailable"), now=NOW) == "retry_wait"
        claim = store.claim_due(1, now=NOW + timedelta(seconds=delay_seconds))[0]

    assert store.mark_retry(claim, RuntimeError("Redis unavailable"), now=NOW) == "stopped"
    assert store.claim_due(1, now=NOW + timedelta(hours=1)) == ()
    with migrated_engine.connect() as connection:
        row = connection.execute(
            select(
                job_dispatches,
                ingestion_runs.c.correlation_id,
                ingestion_runs.c.status.label("run_status"),
                ingestion_runs.c.finished_at.label("run_finished_at"),
            )
            .join(ingestion_runs, ingestion_runs.c.run_id == job_dispatches.c.ingestion_run_id)
            .where(job_dispatches.c.dispatch_id == dispatch_id)
        ).one()
    assert (row.ingestion_run_id, row.dispatch_id, row.correlation_id) == original
    assert row.status == "stopped"
    assert row.attempt_count == 4
    assert row.next_dispatch_at is None
    assert row.lease_expires_at is None
    assert row.dispatch_token is None
    assert row.last_error == "RuntimeError"
    assert row.run_status == "failed"
    assert row.run_finished_at is not None


def test_expired_claim_is_recovered_and_old_token_cannot_acknowledge_it(
    migrated_engine,
) -> None:
    run_id, dispatch_id, correlation_id = _seed_pending_dispatch(
        migrated_engine,
        run_status="running",
        run_lease_expires_at=NOW - timedelta(seconds=1),
    )
    old_token = uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            update(job_dispatches)
            .where(job_dispatches.c.dispatch_id == dispatch_id)
            .values(
                status="dispatching",
                next_dispatch_at=None,
                lease_expires_at=NOW - timedelta(seconds=1),
                dispatch_token=old_token,
                attempt_count=1,
            )
        )
    store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))

    claim = store.claim_due(1, now=NOW)[0]

    assert claim.token != old_token
    assert claim.dispatch == IngestionDispatch(
        dispatch_id=dispatch_id,
        run_id=run_id,
        correlation_id=correlation_id,
    )
    with pytest.raises(DispatchClaimLost):
        store.mark_enqueued(DispatchClaim(dispatch=claim.dispatch, token=old_token))
    store.mark_enqueued(claim)
