"""The historical operator action creates only audited, durable prediction work."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select, update

from quakestrike.application.historical_recovery import (
    AUDIT_ACTION,
    SOURCE_RUN_ID,
    RecoverHistoricalPredictions,
    UnsafeHistoricalRecovery,
)
from quakestrike.domain.features import (
    INPUT_SCHEMA_VERSION,
    HistoryCoverage,
    create_feature_snapshot,
)
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.historical_recovery import SqlAlchemyHistoricalRecovery
from quakestrike.infrastructure.database.tables import (
    audit_logs,
    earthquake_event_revisions,
    earthquake_events,
    ingestion_runs,
    job_dispatches,
    model_releases,
    prediction_jobs,
    source_catalog_evidence,
)

pytestmark = pytest.mark.integration
RELEASE_ID = UUID("a7f2286b-13a2-4708-a04d-4139281a4e1f")
ANCHOR_TIME = datetime(2026, 9, 24, 17, tzinfo=UTC)
INGESTED_AT = ANCHOR_TIME + timedelta(hours=1)
BOOTSTRAP_SHA = "a" * 64


def _revision(connection, run_id, *, event_time, ingested_at, revision_number=1, event_id=None):
    event_id = event_id or uuid4()
    revision_id = uuid4()
    if revision_number == 1:
        connection.execute(
            insert(earthquake_events).values(
                event_id=event_id, first_seen_run_id=run_id, last_seen_run_id=run_id
            )
        )
    connection.execute(
        insert(earthquake_event_revisions).values(
            event_revision_id=revision_id,
            event_id=event_id,
            revision_number=revision_number,
            ingestion_run_id=run_id,
            source_event_group_id=f"2026_0924_{revision_id.hex[:4].upper()}",
            source_url="https://earthquake.phivolcs.dost.gov.ph/example",
            source_time_precision="second",
            event_time=event_time,
            latitude=Decimal("14.000000"),
            longitude=Decimal("121.000000"),
            depth_km=Decimal("10.000"),
            magnitude=Decimal("4.20"),
            location_description="Example",
            prediction_skip_reason=(
                "history_coverage_unavailable" if run_id == SOURCE_RUN_ID else None
            ),
            ingested_at=ingested_at,
        )
    )
    return event_id, revision_id


def _seed(engine, *, bootstrap_end=None, live_start=None):
    bootstrap_id, live_id, correlation_id = uuid4(), uuid4(), uuid4()
    bootstrap_correlation_id = uuid4()
    bootstrap_end = bootstrap_end or datetime(2026, 9, 19, tzinfo=UTC)
    live_start = live_start or datetime(2026, 9, 1, tzinfo=UTC)
    with engine.begin() as connection:
        for run_id, trigger, sha in (
            (bootstrap_id, "backfill", BOOTSTRAP_SHA),
            (SOURCE_RUN_ID, "manual", None),
            (live_id, "scheduled", None),
        ):
            connection.execute(
                insert(ingestion_runs).values(
                    run_id=run_id,
                    trigger_type=trigger,
                    status="succeeded",
                    started_at=INGESTED_AT,
                    finished_at=INGESTED_AT,
                    correlation_id=(
                        correlation_id
                        if run_id == SOURCE_RUN_ID
                        else bootstrap_correlation_id
                        if run_id == bootstrap_id
                        else uuid4()
                    ),
                    bootstrap_snapshot_sha256=sha,
                )
            )
        connection.execute(
            insert(model_releases).values(
                model_release_id=RELEASE_ID,
                version_label="SEIS 1.0.1",
                artifact_manifest_uri="model-artifacts/seis-1.0.1/manifest.json",
                artifact_manifest_hash="b" * 64,
                input_schema_version=INPUT_SCHEMA_VERSION,
                output_schema_version="quakestrike.prediction-output.v2",
            )
        )
        connection.execute(
            insert(source_catalog_evidence).values(
                run_id=live_id,
                source_url="https://earthquake.phivolcs.dost.gov.ph/",
                catalog_sha256="c" * 64,
                retrieved_at=ANCHOR_TIME + timedelta(days=1),
                coverage_start=live_start,
                coverage_end=ANCHOR_TIME + timedelta(hours=23),
                accepted_rows=1,
            )
        )
        _, candidate_id = _revision(
            connection, SOURCE_RUN_ID, event_time=ANCHOR_TIME, ingested_at=INGESTED_AT
        )
    coverage = HistoryCoverage(datetime(2026, 8, 1, tzinfo=UTC), bootstrap_end, True)
    store = SqlAlchemyHistoricalRecovery(
        create_session_factory(engine),
        target_release_id=RELEASE_ID,
        bootstrap_run_id=bootstrap_id,
    )
    recovery = RecoverHistoricalPredictions(
        store,
        target_release_id=RELEASE_ID,
        bootstrap_run_id=bootstrap_id,
        bootstrap_sha256=BOOTSTRAP_SHA,
        bootstrap_correlation_id=bootstrap_correlation_id,
        bootstrap_coverage=coverage,
    )
    return recovery, candidate_id, live_id


def test_dry_run_then_apply_and_repeat_preserves_skip_and_audits(migrated_engine):
    recovery, revision_id, live_id = _seed(migrated_engine)
    with migrated_engine.begin() as connection:
        history_event, _ = _revision(
            connection,
            live_id,
            event_time=ANCHOR_TIME - timedelta(hours=2),
            ingested_at=INGESTED_AT - timedelta(minutes=1),
        )
        _revision(
            connection,
            live_id,
            event_time=ANCHOR_TIME - timedelta(hours=1),
            ingested_at=INGESTED_AT + timedelta(days=1),
            revision_number=2,
            event_id=history_event,
        )
    preview = recovery.run(apply=False)
    assert preview["eligible"] == 1
    assert preview.get("superseded", 0) == 0
    assert recovery.run(apply=True)["created"] == 1
    assert recovery.run(apply=True)["reused"] == 1
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(prediction_jobs)) == 1
        assert connection.scalar(select(func.count()).select_from(job_dispatches)) == 1
        job = connection.execute(select(prediction_jobs)).one()
        assert job.event_revision_id == revision_id
        assert job.input_snapshot_json["catalog_m1_plus_count_past_24h"] == 1
        assert connection.scalar(select(func.count()).select_from(audit_logs)) == 1
        assert connection.execute(select(audit_logs)).one().action == AUDIT_ACTION
        assert (
            connection.scalar(
                select(earthquake_event_revisions.c.prediction_skip_reason).where(
                    earthquake_event_revisions.c.event_revision_id == revision_id
                )
            )
            == "history_coverage_unavailable"
        )


def test_recovery_rejects_gap_in_seven_day_source_coverage(migrated_engine):
    recovery, _, _ = _seed(
        migrated_engine,
        bootstrap_end=datetime(2026, 9, 16, tzinfo=UTC),
        live_start=datetime(2026, 9, 18, tzinfo=UTC),
    )
    result = recovery.run(apply=True)
    assert result["history_starts_after_required_window"] == 1
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(prediction_jobs)) == 0


def test_superseded_revision_is_excluded(migrated_engine):
    recovery, candidate_id, live_id = _seed(migrated_engine)
    with migrated_engine.begin() as connection:
        event_id = connection.scalar(
            select(earthquake_event_revisions.c.event_id).where(
                earthquake_event_revisions.c.event_revision_id == candidate_id
            )
        )
        _revision(
            connection,
            live_id,
            event_time=ANCHOR_TIME,
            ingested_at=INGESTED_AT + timedelta(days=1),
            revision_number=2,
            event_id=event_id,
        )
    assert recovery.run(apply=True)["superseded"] == 1


def test_recovery_batches_new_jobs_without_duplicating_prior_batch(migrated_engine):
    recovery, _, _ = _seed(migrated_engine)
    with migrated_engine.begin() as connection:
        _revision(
            connection,
            SOURCE_RUN_ID,
            event_time=ANCHOR_TIME + timedelta(minutes=1),
            ingested_at=INGESTED_AT + timedelta(minutes=1),
        )
    first = recovery.run(apply=True, max_new_jobs=1)
    assert first["created"] == 1
    assert first["deferred"] == 1
    second = recovery.run(apply=True, max_new_jobs=1)
    assert second["reused"] == 1
    assert second["created"] == 1
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(audit_logs)) == 2


def test_bootstrap_correlation_must_match_durable_run(migrated_engine):
    recovery, _, _ = _seed(migrated_engine)
    with migrated_engine.begin() as connection:
        connection.execute(
            update(ingestion_runs)
            .where(ingestion_runs.c.trigger_type == "backfill")
            .values(correlation_id=uuid4())
        )
    with pytest.raises(UnsafeHistoricalRecovery):
        recovery.run(apply=False)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_run_id", str(uuid4())),
        ("bootstrap_snapshot_sha256", "f" * 64),
        ("model_release_id", str(uuid4())),
        ("input_snapshot_hash", "f" * 64),
        ("coverage_run_ids", [str(uuid4())]),
        ("coverage_end", "changed"),
        ("historical_no_alert", False),
    ],
)
def test_rerun_rejects_changed_audit_evidence(migrated_engine, field, value):
    recovery, _, _ = _seed(migrated_engine)
    assert recovery.run(apply=True)["created"] == 1
    with migrated_engine.begin() as connection:
        audit = connection.execute(select(audit_logs)).one()
        changed = dict(audit._mapping["metadata"])
        changed[field] = value
        connection.execute(
            update(audit_logs)
            .where(audit_logs.c.audit_id == audit.audit_id)
            .values(metadata=changed)
        )
    with pytest.raises(UnsafeHistoricalRecovery):
        recovery.run(apply=True)


def test_rerun_accepts_original_evidence_after_new_live_coverage(migrated_engine):
    recovery, _, _ = _seed(migrated_engine)
    assert recovery.run(apply=True)["created"] == 1
    new_run_id = uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(ingestion_runs).values(
                run_id=new_run_id,
                trigger_type="scheduled",
                status="succeeded",
                started_at=INGESTED_AT + timedelta(days=1),
                finished_at=INGESTED_AT + timedelta(days=1),
                correlation_id=uuid4(),
            )
        )
        connection.execute(
            insert(source_catalog_evidence).values(
                run_id=new_run_id,
                source_url="https://earthquake.phivolcs.dost.gov.ph/",
                catalog_sha256="e" * 64,
                retrieved_at=ANCHOR_TIME + timedelta(days=2),
                coverage_start=datetime(2026, 9, 1, tzinfo=UTC),
                coverage_end=ANCHOR_TIME + timedelta(days=1),
                accepted_rows=1,
            )
        )
    assert recovery.run(apply=True)["reused"] == 1


def test_rerun_validates_work_even_after_later_event_revision(migrated_engine):
    recovery, revision_id, live_id = _seed(migrated_engine)
    assert recovery.run(apply=True)["created"] == 1
    with migrated_engine.begin() as connection:
        event_id = connection.scalar(
            select(earthquake_event_revisions.c.event_id).where(
                earthquake_event_revisions.c.event_revision_id == revision_id
            )
        )
        _revision(
            connection,
            live_id,
            event_time=ANCHOR_TIME,
            ingested_at=INGESTED_AT + timedelta(days=1),
            revision_number=2,
            event_id=event_id,
        )
    assert recovery.run(apply=True)["reused"] == 1


def test_conflict_after_first_commit_keeps_prior_audit(migrated_engine):
    recovery, _, _ = _seed(migrated_engine)
    with migrated_engine.begin() as connection:
        _, second_id = _revision(
            connection,
            SOURCE_RUN_ID,
            event_time=ANCHOR_TIME + timedelta(minutes=1),
            ingested_at=INGESTED_AT + timedelta(minutes=1),
        )
        conflicting_snapshot = create_feature_snapshot(
            {
                "anchor_magnitude": 4.2,
                "anchor_depth_km": 10,
                "anchor_latitude": 14,
                "anchor_longitude": 121,
                "anchor_time_is_minute_precision": 0,
                "catalog_m1_plus_count_past_1h": 0,
                "catalog_m1_plus_count_past_24h": 0,
                "catalog_m1_plus_count_past_7d": 0,
                "local_m1_plus_count_past_24h_within_50km": 0,
                "local_m1_plus_count_past_24h_within_100km": 0,
            }
        )
        connection.execute(
            insert(prediction_jobs).values(
                job_id=uuid4(),
                event_revision_id=second_id,
                model_release_id=RELEASE_ID,
                input_snapshot_hash=conflicting_snapshot.sha256,
                input_snapshot_json=dict(conflicting_snapshot.values),
                idempotency_key=f"conflict:{second_id}",
                correlation_id=uuid4(),
            )
        )
    with pytest.raises(UnsafeHistoricalRecovery):
        recovery.run(apply=True)
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(audit_logs)) == 1
        assert connection.scalar(select(func.count()).select_from(prediction_jobs)) == 2
