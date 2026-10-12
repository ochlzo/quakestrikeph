"""Retention clears successful scheduled progress and aged terminal progress."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select, text, update

from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.database.tables import ingestion_run_inputs, ingestion_runs

pytestmark = pytest.mark.integration
RETENTION_SCRIPT = (
    Path(__file__).resolve().parents[3] / "database/maintenance/ingestion-checkpoint-retention.sql"
).read_text(encoding="utf-8")
RETENTION_SQL = "WITH doomed" + RETENTION_SCRIPT.split("WITH doomed", 1)[1].split(";", 1)[0]


def _cleanup(connection) -> int:
    connection.execute(text("SELECT pg_advisory_xact_lock(5173835459)"))
    return connection.scalar(text(RETENTION_SQL))


def test_checkpoint_cleanup_is_batched_and_preserves_other_run_types(migrated_engine) -> None:
    now = datetime.now(UTC)
    old = now - timedelta(days=31)
    cases = (
        ("scheduled", "succeeded", old, 5001),
        ("scheduled", "succeeded", now, 1),
        ("scheduled", "failed", old, 1),
        ("manual", "succeeded", old, 1),
        ("backfill", "succeeded", old, 1),
        ("backfill", "failed", now - timedelta(days=29), 1),
        ("manual", "cancelled", now - timedelta(days=29), 1),
        ("scheduled", "pending", None, 1),
    )
    run_ids = []
    with migrated_engine.begin() as connection:
        for trigger_type, status, finished_at, count in cases:
            run_id = uuid4()
            run_ids.append(run_id)
            connection.execute(
                insert(ingestion_runs).values(
                    run_id=run_id,
                    trigger_type=trigger_type,
                    status=status,
                    requested_at=(finished_at or old) - timedelta(minutes=4),
                    started_at=(finished_at - timedelta(minutes=3)) if finished_at else None,
                    finished_at=finished_at,
                    events_found=count,
                    events_rejected=count,
                    correlation_id=uuid4(),
                    bootstrap_snapshot_sha256="a" * 64 if trigger_type == "backfill" else None,
                )
            )
            connection.execute(
                insert(ingestion_run_inputs),
                [
                    {"run_id": run_id, "input_key": f"row:{number}", "outcome": "rejected"}
                    for number in range(count)
                ],
            )

    with migrated_engine.begin() as connection:
        assert _cleanup(connection) == 5000
        assert _cleanup(connection) == 5
        assert _cleanup(connection) == 0
        assert connection.scalar(select(func.count()).select_from(ingestion_run_inputs)) == 3
        assert connection.scalar(select(func.count()).select_from(ingestion_runs)) == 8
        for run_id in run_ids[5:]:
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(ingestion_run_inputs)
                    .where(ingestion_run_inputs.c.run_id == run_id)
                )
                == 1
            )


class _VerifiedRelease:
    def is_verified(self, _release_id) -> bool:
        return True


@pytest.mark.parametrize("age_days", [29, 31])
def test_failed_backfill_requeue_respects_checkpoint_window(migrated_engine, age_days) -> None:
    store = SqlAlchemyIngestionTransactions(
        create_session_factory(migrated_engine), model_release_verifier=_VerifiedRelease()
    )
    run_id, correlation_id, snapshot_hash = uuid4(), uuid4(), "b" * 64
    store.create_backfill_run(run_id, correlation_id, snapshot_hash)
    with migrated_engine.begin() as connection:
        connection.execute(
            update(ingestion_runs)
            .where(ingestion_runs.c.run_id == run_id)
            .values(
                status="failed",
                started_at=datetime.now(UTC) - timedelta(days=age_days, minutes=1),
                finished_at=datetime.now(UTC) - timedelta(days=age_days),
            )
        )
        connection.execute(
            insert(ingestion_run_inputs).values(
                run_id=run_id, input_key="row:retry", outcome="rejected"
            )
        )
        assert _cleanup(connection) == (1 if age_days == 31 else 0)

    requeued = store.requeue_backfill_run(run_id, correlation_id, snapshot_hash)
    assert (requeued.run_id == run_id) is (age_days == 29)
    assert requeued.status == "pending"
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ingestion_run_inputs)) == (
            1 if age_days == 29 else 0
        )
        assert connection.scalar(select(func.count()).select_from(ingestion_runs)) == (
            1 if age_days == 29 else 2
        )
