from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, insert, inspect, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from quakestrike.infrastructure.database.tables import (
    earthquake_event_revisions,
    earthquake_events,
    ingestion_runs,
    job_dispatches,
    model_releases,
    prediction_jobs,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 16, tzinfo=UTC)
HASH = "a" * 64


def _failed(engine, statement) -> None:
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(statement)


def _run_values(**changes):
    values = {
        "run_id": uuid4(),
        "trigger_type": "backfill",
        "status": "succeeded",
        "started_at": NOW,
        "finished_at": NOW,
        "correlation_id": uuid4(),
    }
    values.update(changes)
    return values


@pytest.fixture
def parents(migrated_engine) -> dict[str, UUID]:
    ids = {
        "run": uuid4(),
        "event": uuid4(),
        "revision": uuid4(),
        "release": uuid4(),
    }
    with migrated_engine.begin() as connection:
        connection.execute(insert(ingestion_runs).values(**_run_values(run_id=ids["run"])))
        connection.execute(
            insert(earthquake_events).values(
                event_id=ids["event"],
                first_seen_run_id=ids["run"],
                last_seen_run_id=ids["run"],
            )
        )
        connection.execute(
            insert(earthquake_event_revisions).values(
                event_revision_id=ids["revision"],
                event_id=ids["event"],
                revision_number=1,
                ingestion_run_id=ids["run"],
                source_bulletin_id="2026_0831_1609_B1",
                source_event_group_id="2026_0831_1609",
                source_url="https://earthquake.phivolcs.dost.gov.ph/example",
                source_time_precision="minute",
                event_time=NOW,
                latitude=Decimal("14.123456"),
                longitude=Decimal("121.123456"),
                depth_km=Decimal("10.000"),
                magnitude=Decimal("4.20"),
                location_description="Example location",
            )
        )
        connection.execute(
            insert(model_releases).values(
                model_release_id=ids["release"],
                version_label="SEIS 1.0",
                artifact_manifest_uri="model-artifacts/seis-1.0/manifest.json",
                artifact_manifest_hash=HASH,
                input_schema_version="1",
                output_schema_version="1",
            )
        )
    return ids


def _revision_values(parents: dict[str, UUID], **changes):
    values = {
        "event_revision_id": uuid4(),
        "event_id": parents["event"],
        "revision_number": 2,
        "ingestion_run_id": parents["run"],
        "source_bulletin_id": "2026_0831_1609_B2",
        "source_event_group_id": "2026_0831_1609",
        "source_url": "https://earthquake.phivolcs.dost.gov.ph/example-b2",
        "source_time_precision": "second",
        "event_time": NOW,
        "latitude": Decimal("14.100000"),
        "longitude": Decimal("121.100000"),
        "depth_km": Decimal("11.000"),
        "magnitude": Decimal("4.30"),
        "location_description": "Example location",
    }
    values.update(changes)
    return values


def _job_values(parents: dict[str, UUID], **changes):
    values = {
        "job_id": uuid4(),
        "event_revision_id": parents["revision"],
        "model_release_id": parents["release"],
        "input_snapshot_hash": HASH,
        "input_snapshot_json": {"anchor_magnitude": 4.2},
        "idempotency_key": str(uuid4()),
        "correlation_id": uuid4(),
    }
    values.update(changes)
    return values


@pytest.mark.parametrize(
    ("changes"),
    [
        {"attempt_count": -1},
        {"events_found": -1},
        {"trigger_type": ""},
        {"status": "running", "started_at": None, "finished_at": None},
        {"status": "retry_wait", "finished_at": NOW},
    ],
)
def test_ingestion_run_state_and_counter_constraints(migrated_engine, changes) -> None:
    _failed(migrated_engine, insert(ingestion_runs).values(**_run_values(**changes)))


@pytest.mark.parametrize(
    "changes",
    [
        {"source_bulletin_id": None, "source_event_group_id": None},
        {"revision_number": 0},
        {"latitude": Decimal("90.000001")},
        {"longitude": Decimal("-180.000001")},
        {"depth_km": Decimal("-0.001")},
        {"source_time_precision": "millisecond"},
        {"source_bulletin_id": "lowercase"},
        {"source_url": "   "},
        {"location_description": ""},
        {"origin": "UNKNOWN"},
    ],
)
def test_revision_validation_constraints(migrated_engine, parents, changes) -> None:
    _failed(
        migrated_engine,
        insert(earthquake_event_revisions).values(**_revision_values(parents, **changes)),
    )


@pytest.mark.parametrize("column", ["latitude", "longitude", "depth_km", "magnitude"])
@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_revision_rejects_nonfinite_observations(migrated_engine, parents, column, value) -> None:
    with pytest.raises(DBAPIError), migrated_engine.begin() as connection:
        connection.execute(
            insert(earthquake_event_revisions).values(
                **_revision_values(parents, **{column: value})
            )
        )


def test_revision_identity_constraints_and_group_index(migrated_engine, parents) -> None:
    _failed(
        migrated_engine,
        insert(earthquake_event_revisions).values(
            **_revision_values(parents, source_bulletin_id="2026_0831_1609_B1")
        ),
    )
    _failed(
        migrated_engine,
        insert(earthquake_event_revisions).values(
            **_revision_values(parents, source_bulletin_id=None, revision_number=1)
        ),
    )
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(earthquake_event_revisions).values(
                **_revision_values(
                    parents,
                    source_bulletin_id=None,
                    source_event_group_id="2026_0831_1609",
                )
            )
        )
    indexes = {
        item["name"]: item
        for item in inspect(migrated_engine).get_indexes("earthquake_event_revisions")
    }
    assert indexes["uq_event_revisions_source_bulletin_id"]["unique"] is True
    assert indexes["ix_event_revisions_source_event_group_id"]["unique"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"input_snapshot_hash": "not-a-hash"},
        {"input_snapshot_json": [1, 2]},
        {"idempotency_key": ""},
        {"status": "retry_wait", "next_attempt_at": None},
        {"status": "failed", "completed_at": None},
    ],
)
def test_prediction_job_validation_constraints(migrated_engine, parents, changes) -> None:
    _failed(migrated_engine, insert(prediction_jobs).values(**_job_values(parents, **changes)))


def test_prediction_job_idempotency_constraints(migrated_engine, parents) -> None:
    first = _job_values(parents)
    with migrated_engine.begin() as connection:
        connection.execute(insert(prediction_jobs).values(**first))
    _failed(
        migrated_engine,
        insert(prediction_jobs).values(
            **_job_values(
                parents, input_snapshot_hash="b" * 64, idempotency_key=first["idempotency_key"]
            )
        ),
    )
    _failed(
        migrated_engine,
        insert(prediction_jobs).values(**_job_values(parents, idempotency_key=str(uuid4()))),
    )


def test_dispatch_target_state_and_uniqueness_constraints(migrated_engine, parents) -> None:
    job = _job_values(parents)
    with migrated_engine.begin() as connection:
        connection.execute(insert(prediction_jobs).values(**job))
        connection.execute(
            insert(job_dispatches).values(dispatch_id=uuid4(), prediction_job_id=job["job_id"])
        )
    _failed(migrated_engine, insert(job_dispatches).values(dispatch_id=uuid4()))
    _failed(
        migrated_engine,
        insert(job_dispatches).values(
            dispatch_id=uuid4(),
            ingestion_run_id=parents["run"],
            prediction_job_id=job["job_id"],
        ),
    )
    _failed(
        migrated_engine,
        insert(job_dispatches).values(dispatch_id=uuid4(), alert_job_id=uuid4()),
    )
    _failed(
        migrated_engine,
        insert(job_dispatches).values(
            dispatch_id=uuid4(), ingestion_run_id=parents["run"], attempt_count=-1
        ),
    )
    _failed(
        migrated_engine,
        insert(job_dispatches).values(
            dispatch_id=uuid4(),
            ingestion_run_id=parents["run"],
            status="dispatching",
        ),
    )
    _failed(
        migrated_engine,
        insert(job_dispatches).values(dispatch_id=uuid4(), prediction_job_id=job["job_id"]),
    )


def test_foreign_keys_restrict_invalid_parents_updates_and_deletes(
    migrated_engine, parents
) -> None:
    _failed(
        migrated_engine,
        insert(earthquake_events).values(
            event_id=uuid4(), first_seen_run_id=uuid4(), last_seen_run_id=parents["run"]
        ),
    )
    _failed(
        migrated_engine,
        delete(ingestion_runs).where(ingestion_runs.c.run_id == parents["run"]),
    )
    _failed(
        migrated_engine,
        update(ingestion_runs)
        .where(ingestion_runs.c.run_id == parents["run"])
        .values(run_id=uuid4()),
    )


def test_queue_partial_indexes_exist(migrated_engine) -> None:
    run_indexes = {item["name"] for item in inspect(migrated_engine).get_indexes("ingestion_runs")}
    dispatch_indexes = {
        item["name"] for item in inspect(migrated_engine).get_indexes("job_dispatches")
    }
    assert "uq_ingestion_runs_one_active" in run_indexes
    assert "ix_ingestion_runs_running_lease" in run_indexes
    assert {"ix_job_dispatches_ready", "ix_job_dispatches_dispatching_lease"} <= dispatch_indexes
