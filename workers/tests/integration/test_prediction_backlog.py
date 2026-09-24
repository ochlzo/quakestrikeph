"""Operator recovery of work tied to the retired SEIS 1.0 output contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select

from quakestrike.domain.features import INPUT_SCHEMA_VERSION, create_feature_snapshot
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.prediction_backlog import (
    SqlAlchemyPredictionBacklogReissuer,
)
from quakestrike.infrastructure.database.tables import (
    alert_jobs,
    audit_logs,
    earthquake_bulletin_event_identities,
    earthquake_event_revisions,
    earthquake_events,
    forecasts,
    ingestion_runs,
    job_dispatches,
    model_releases,
    prediction_attempts,
    prediction_jobs,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
LEGACY_RELEASE_ID = UUID("2f532893-7a25-4f18-814c-91d66f38dac4")
TARGET_RELEASE_ID = UUID("a7f2286b-13a2-4708-a04d-4139281a4e1f")
FEATURES = {
    "anchor_magnitude": 4.2,
    "anchor_depth_km": 10,
    "anchor_latitude": 14.123456,
    "anchor_longitude": 121.123456,
    "anchor_time_is_minute_precision": 1,
    "catalog_m1_plus_count_past_1h": 0,
    "catalog_m1_plus_count_past_24h": 0,
    "catalog_m1_plus_count_past_7d": 0,
    "local_m1_plus_count_past_24h_within_50km": 0,
    "local_m1_plus_count_past_24h_within_100km": 0,
}


def _seed_legacy_job(engine, *, status="pending", error_code=None):
    run_id, event_id, revision_id, job_id, dispatch_id, correlation_id = (uuid4() for _ in range(6))
    snapshot = create_feature_snapshot(FEATURES)
    with engine.begin() as connection:
        for release_id, version, output_schema in (
            (LEGACY_RELEASE_ID, "SEIS 1.0", "quakestrike.prediction-output.v1"),
            (TARGET_RELEASE_ID, "SEIS 1.0.1", "quakestrike.prediction-output.v2"),
        ):
            connection.execute(
                insert(model_releases).values(
                    model_release_id=release_id,
                    version_label=version,
                    artifact_manifest_uri=f"{version}/manifest.json",
                    artifact_manifest_hash="a" * 64,
                    input_schema_version=INPUT_SCHEMA_VERSION,
                    output_schema_version=output_schema,
                )
            )
        connection.execute(
            insert(ingestion_runs).values(
                run_id=run_id,
                trigger_type="manual",
                status="succeeded",
                started_at=NOW,
                finished_at=NOW,
                correlation_id=correlation_id,
            )
        )
        connection.execute(
            insert(earthquake_events).values(
                event_id=event_id,
                first_seen_run_id=run_id,
                last_seen_run_id=run_id,
            )
        )
        connection.execute(
            insert(earthquake_bulletin_event_identities).values(
                source_bulletin_id="2026_0924_1200_B1",
                event_id=event_id,
            )
        )
        connection.execute(
            insert(earthquake_event_revisions).values(
                event_revision_id=revision_id,
                event_id=event_id,
                revision_number=1,
                ingestion_run_id=run_id,
                source_bulletin_id="2026_0924_1200_B1",
                source_event_group_id="2026_0924_1200",
                source_url="https://earthquake.phivolcs.dost.gov.ph/example",
                source_time_precision="minute",
                event_time=NOW,
                latitude=Decimal("14.123456"),
                longitude=Decimal("121.123456"),
                depth_km=Decimal("10.000"),
                magnitude=Decimal("4.20"),
                location_description="Example",
            )
        )
        connection.execute(
            insert(prediction_jobs).values(
                job_id=job_id,
                event_revision_id=revision_id,
                model_release_id=LEGACY_RELEASE_ID,
                input_snapshot_hash=snapshot.sha256,
                input_snapshot_json=dict(snapshot.values),
                idempotency_key=f"legacy:{job_id}",
                status=status,
                next_attempt_at=NOW + timedelta(minutes=1) if status == "retry_wait" else None,
                completed_at=NOW if status == "failed" else None,
                last_error_code=error_code,
                last_error_message="Legacy schema cannot be served." if error_code else None,
                correlation_id=correlation_id,
            )
        )
        connection.execute(
            insert(job_dispatches).values(
                dispatch_id=dispatch_id,
                prediction_job_id=job_id,
                status="stopped" if status == "failed" else "enqueued",
                next_dispatch_at=None,
                last_dispatched_at=NOW,
            )
        )
    return job_id, dispatch_id, revision_id, correlation_id, snapshot


def _run(engine):
    return SqlAlchemyPredictionBacklogReissuer(
        create_session_factory(engine), target_release_id=TARGET_RELEASE_ID
    ).run()


@pytest.mark.parametrize("status", ["pending", "retry_wait"])
def test_reissue_preserves_source_and_creates_distinct_v2_work(migrated_engine, status):
    old_job_id, old_dispatch_id, revision_id, correlation_id, snapshot = _seed_legacy_job(
        migrated_engine, status=status
    )

    _run(migrated_engine)

    with migrated_engine.connect() as connection:
        jobs = connection.execute(select(prediction_jobs)).all()
        assert len(jobs) == 2
        old_job = next(row for row in jobs if row.job_id == old_job_id)
        new_job = next(row for row in jobs if row.job_id != old_job_id)
        dispatches = connection.execute(select(job_dispatches)).all()
        old_dispatch = next(row for row in dispatches if row.dispatch_id == old_dispatch_id)
        new_dispatch = next(row for row in dispatches if row.dispatch_id != old_dispatch_id)

        assert old_job.model_release_id == LEGACY_RELEASE_ID
        assert old_job.event_revision_id == revision_id
        assert old_job.input_snapshot_hash == snapshot.sha256
        assert old_job.input_snapshot_json == dict(snapshot.values)
        assert old_job.status == "cancelled"
        assert old_job.completed_at is not None
        assert old_job.next_attempt_at is None
        assert old_job.last_error_code == "reissued_for_release"
        assert old_dispatch.status == "stopped"
        assert old_dispatch.prediction_job_id == old_job_id

        assert new_job.model_release_id == TARGET_RELEASE_ID
        assert new_job.event_revision_id == revision_id
        assert new_job.input_snapshot_hash == snapshot.sha256
        assert new_job.input_snapshot_json == dict(snapshot.values)
        assert new_job.correlation_id == correlation_id
        assert new_job.status == "pending"
        assert new_job.idempotency_key != old_job.idempotency_key
        assert new_dispatch.prediction_job_id == new_job.job_id
        assert new_dispatch.status == "pending"
        assert new_dispatch.dispatch_id != old_dispatch_id
        assert connection.scalar(select(func.count()).select_from(forecasts)) == 0
        assert connection.scalar(select(func.count()).select_from(alert_jobs)) == 0
        audit = connection.execute(select(audit_logs)).one()
        assert audit.actor_type == "system"
        assert str(old_job_id) in str(audit.metadata)
        assert str(new_job.job_id) in str(audit.metadata)


@pytest.mark.parametrize("error_code", ["unsupported_schema", "release_mismatch"])
def test_reissue_recovers_legacy_job_failed_by_v2_worker(migrated_engine, error_code):
    old_job_id, _, _, _, _ = _seed_legacy_job(
        migrated_engine, status="failed", error_code=error_code
    )

    _run(migrated_engine)

    with migrated_engine.connect() as connection:
        old_job = connection.execute(
            select(prediction_jobs).where(prediction_jobs.c.job_id == old_job_id)
        ).one()
        new_job = connection.execute(
            select(prediction_jobs).where(prediction_jobs.c.model_release_id == TARGET_RELEASE_ID)
        ).one()
        assert old_job.status == "cancelled"
        assert old_job.last_error_code == "reissued_for_release"
        assert new_job.status == "pending"


def test_reissue_is_idempotent_on_operator_rerun(migrated_engine):
    _seed_legacy_job(migrated_engine)

    _run(migrated_engine)
    with migrated_engine.connect() as connection:
        first_job_ids = set(connection.scalars(select(prediction_jobs.c.job_id)))
        first_dispatch_ids = set(connection.scalars(select(job_dispatches.c.dispatch_id)))
        first_audit_ids = set(connection.scalars(select(audit_logs.c.audit_id)))

    _run(migrated_engine)

    with migrated_engine.connect() as connection:
        assert set(connection.scalars(select(prediction_jobs.c.job_id))) == first_job_ids
        assert set(connection.scalars(select(job_dispatches.c.dispatch_id))) == first_dispatch_ids
        assert set(connection.scalars(select(audit_logs.c.audit_id))) == first_audit_ids


def test_reissue_reuses_existing_matching_v2_work(migrated_engine):
    old_job_id, _, revision_id, correlation_id, snapshot = _seed_legacy_job(migrated_engine)
    existing_job_id, existing_dispatch_id = uuid4(), uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(prediction_jobs).values(
                job_id=existing_job_id,
                event_revision_id=revision_id,
                model_release_id=TARGET_RELEASE_ID,
                input_snapshot_hash=snapshot.sha256,
                input_snapshot_json=dict(snapshot.values),
                idempotency_key=f"prediction:{revision_id}:{TARGET_RELEASE_ID}:{snapshot.sha256}",
                correlation_id=correlation_id,
            )
        )
        connection.execute(
            insert(job_dispatches).values(
                dispatch_id=existing_dispatch_id,
                prediction_job_id=existing_job_id,
                status="pending",
                next_dispatch_at=NOW,
            )
        )

    result = _run(migrated_engine)

    assert result == {"reissued": 0, "reused": 1}
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(prediction_jobs)) == 2
        assert connection.scalar(select(func.count()).select_from(job_dispatches)) == 2
        assert (
            connection.execute(
                select(prediction_jobs.c.status).where(prediction_jobs.c.job_id == old_job_id)
            ).scalar_one()
            == "cancelled"
        )
        existing = connection.execute(
            select(prediction_jobs).where(prediction_jobs.c.job_id == existing_job_id)
        ).one()
        assert existing.status == "pending"
        assert existing.input_snapshot_json == dict(snapshot.values)
        assert (
            connection.execute(
                select(job_dispatches.c.status).where(
                    job_dispatches.c.dispatch_id == existing_dispatch_id
                )
            ).scalar_one()
            == "pending"
        )
        audit = connection.execute(select(audit_logs)).one()
        assert audit.metadata["new_job_id"] == str(existing_job_id)
        assert audit.metadata["new_dispatch_id"] == str(existing_dispatch_id)


def test_running_legacy_job_requires_operator_to_quiesce_workers(migrated_engine):
    job_id, dispatch_id, _, _, _ = _seed_legacy_job(migrated_engine)
    with migrated_engine.begin() as connection:
        connection.execute(
            prediction_jobs.update()
            .where(prediction_jobs.c.job_id == job_id)
            .values(status="running")
        )
        connection.execute(
            insert(prediction_attempts).values(
                attempt_id=uuid4(),
                job_id=job_id,
                attempt_number=1,
                status="running",
                started_at=NOW,
                lease_expires_at=NOW + timedelta(hours=1),
                worker_execution_id=uuid4(),
            )
        )

    with pytest.raises((ValueError, RuntimeError)):
        _run(migrated_engine)

    with migrated_engine.connect() as connection:
        job = connection.execute(select(prediction_jobs)).one()
        dispatch = connection.execute(
            select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch_id)
        ).one()
        assert job.job_id == job_id
        assert job.status == "running"
        assert dispatch.status == "enqueued"
        assert connection.scalar(select(func.count()).select_from(prediction_jobs)) == 1
        assert connection.scalar(select(func.count()).select_from(audit_logs)) == 0
