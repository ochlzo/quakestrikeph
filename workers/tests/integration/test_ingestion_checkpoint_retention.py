"""Retention removes only old successful scheduled-run retry checkpoints."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select, text

from quakestrike.infrastructure.database.tables import ingestion_run_inputs, ingestion_runs

pytestmark = pytest.mark.integration
RETENTION_SQL = (
    Path(__file__).resolve().parents[3] / "infrastructure/backup/ingestion-checkpoint-retention.sql"
).read_text(encoding="utf-8")


def test_checkpoint_cleanup_is_batched_and_preserves_other_run_types(migrated_engine) -> None:
    now = datetime.now(UTC)
    old = now - timedelta(days=2)
    cases = (
        ("scheduled", "succeeded", old, 5001),
        ("scheduled", "succeeded", now, 1),
        ("scheduled", "failed", old, 1),
        ("manual", "succeeded", old, 1),
        ("backfill", "succeeded", old, 1),
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
                    requested_at=finished_at - timedelta(minutes=4),
                    started_at=finished_at - timedelta(minutes=3),
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
        assert connection.scalar(text(RETENTION_SQL)) == 5000
        assert connection.scalar(text(RETENTION_SQL)) == 1
        assert connection.scalar(text(RETENTION_SQL)) == 0
        assert connection.scalar(select(func.count()).select_from(ingestion_run_inputs)) == 4
        assert connection.scalar(select(func.count()).select_from(ingestion_runs)) == 5
        for run_id in run_ids[1:]:
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(ingestion_run_inputs)
                    .where(ingestion_run_inputs.c.run_id == run_id)
                )
                == 1
            )
