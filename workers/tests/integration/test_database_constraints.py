from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, insert, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from quakestrike.domain.features import feature_snapshot_hash
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
    prediction_jobs,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 16, tzinfo=UTC)
HASH = "a" * 64
VALID_SNAPSHOT = {
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
VALID_SNAPSHOT_HASH = "644baaa1a8d7368eac18d1a505ebebc533d17bc13742e6f8634d65726ebb6c35"


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
        "bootstrap_snapshot_sha256": VALID_SNAPSHOT_HASH,
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
            insert(earthquake_bulletin_event_identities).values(
                source_bulletin_id="2026_0831_1609_B1",
                event_id=ids["event"],
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
        "input_snapshot_hash": VALID_SNAPSHOT_HASH,
        "input_snapshot_json": dict(VALID_SNAPSHOT),
        "idempotency_key": str(uuid4()),
        "correlation_id": uuid4(),
    }
    values.update(changes)
    return values


def _forecast_values(job_id: UUID, **changes):
    values = {
        "forecast_id": uuid4(),
        "job_id": job_id,
        "window_start": NOW,
        "window_end": NOW + timedelta(hours=24),
        "probability_m1_plus_24h": 0.5,
        "expected_m1_plus_count_24h": 2.0,
        "probability_m4_plus_24h": 0.25,
        "probability_m5_plus_24h": 0.1,
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


def test_backfill_run_requires_a_snapshot_hash(migrated_engine) -> None:
    _failed(
        migrated_engine,
        insert(ingestion_runs).values(
            **_run_values(
                trigger_type="backfill",
                bootstrap_snapshot_sha256=None,
            )
        ),
    )


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


def test_revision_identity_map_allows_enrichment_and_rejects_cross_event_rows(
    migrated_engine, parents
) -> None:
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(earthquake_event_revisions).values(
                **_revision_values(parents, source_bulletin_id="2026_0831_1609_B1")
            )
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
                    revision_number=3,
                )
            )
        )
        other_event_id = uuid4()
        connection.execute(
            insert(earthquake_events).values(
                event_id=other_event_id,
                first_seen_run_id=parents["run"],
                last_seen_run_id=parents["run"],
            )
        )
    _failed(
        migrated_engine,
        insert(earthquake_event_revisions).values(
            **_revision_values(
                parents,
                event_id=other_event_id,
                revision_number=1,
                source_bulletin_id="2026_0831_1609_B1",
            )
        ),
    )
    indexes = {
        item["name"]: item
        for item in inspect(migrated_engine).get_indexes("earthquake_event_revisions")
    }
    assert indexes["ix_event_revisions_source_bulletin_id"]["unique"] is False
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


@pytest.mark.parametrize(
    "snapshot",
    [
        {"anchor_magnitude": 4.2},
        {**VALID_SNAPSHOT, "unexpected": 0},
        {key: value for key, value in VALID_SNAPSHOT.items() if key != "anchor_depth_km"},
    ],
)
def test_prediction_job_rejects_placeholder_extra_and_missing_snapshots(
    migrated_engine,
    parents,
    snapshot,
) -> None:
    _failed(
        migrated_engine,
        insert(prediction_jobs).values(
            **_job_values(
                parents,
                input_snapshot_json=snapshot,
                input_snapshot_hash=VALID_SNAPSHOT_HASH,
            )
        ),
    )


@pytest.mark.parametrize(
    "snapshot",
    [
        {**VALID_SNAPSHOT, "anchor_depth_km": -1},
        {**VALID_SNAPSHOT, "anchor_latitude": 90.000001},
        {**VALID_SNAPSHOT, "anchor_longitude": -180.000001},
        {**VALID_SNAPSHOT, "catalog_m1_plus_count_past_24h": -1},
        {**VALID_SNAPSHOT, "catalog_m1_plus_count_past_7d": 1.5},
        {**VALID_SNAPSHOT, "anchor_time_is_minute_precision": 2},
        {**VALID_SNAPSHOT, "anchor_magnitude": "4.2"},
    ],
)
def test_prediction_job_rejects_invalid_snapshot_types_and_ranges(
    migrated_engine,
    parents,
    snapshot,
) -> None:
    _failed(
        migrated_engine,
        insert(prediction_jobs).values(
            **_job_values(
                parents,
                input_snapshot_json=snapshot,
                input_snapshot_hash=VALID_SNAPSHOT_HASH,
            )
        ),
    )


def test_prediction_job_accepts_a_valid_snapshot_through_direct_sql(
    migrated_engine,
    parents,
) -> None:
    values = _job_values(parents)

    with migrated_engine.begin() as connection:
        connection.execute(insert(prediction_jobs).values(**values))
        stored = connection.execute(
            select(
                prediction_jobs.c.input_snapshot_json,
                prediction_jobs.c.input_snapshot_hash,
            ).where(prediction_jobs.c.job_id == values["job_id"])
        ).one()

    assert stored.input_snapshot_json == VALID_SNAPSHOT
    assert stored.input_snapshot_hash == VALID_SNAPSHOT_HASH


def test_prediction_job_hash_normalizes_valid_numeric_lexemes(
    migrated_engine,
    parents,
) -> None:
    snapshot = {
        **VALID_SNAPSHOT,
        "anchor_latitude": 90.0,
        "anchor_longitude": 0.000001,
    }
    raw_snapshot = json.dumps(snapshot, separators=(",", ":")).replace(
        '"anchor_longitude":1e-06',
        '"anchor_longitude":0.000001',
    )
    values = _job_values(
        parents,
        input_snapshot_hash=feature_snapshot_hash(snapshot),
    )

    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO prediction_jobs (
                    job_id, event_revision_id, model_release_id, input_snapshot_hash,
                    input_snapshot_json, idempotency_key, correlation_id
                ) VALUES (
                    :job_id, :event_revision_id, :model_release_id, :input_snapshot_hash,
                    CAST(:input_snapshot_json AS jsonb), :idempotency_key, :correlation_id
                )
                """
            ),
            {**values, "input_snapshot_json": raw_snapshot},
        )


def test_prediction_job_snapshot_and_hash_cannot_be_updated(
    migrated_engine,
    parents,
) -> None:
    values = _job_values(parents)
    with migrated_engine.begin() as connection:
        connection.execute(insert(prediction_jobs).values(**values))

    _failed(
        migrated_engine,
        update(prediction_jobs)
        .where(prediction_jobs.c.job_id == values["job_id"])
        .values(input_snapshot_json={**VALID_SNAPSHOT, "anchor_magnitude": 4.3}),
    )
    _failed(
        migrated_engine,
        update(prediction_jobs)
        .where(prediction_jobs.c.job_id == values["job_id"])
        .values(input_snapshot_hash="b" * 64),
    )


def test_prediction_job_rejects_a_schema_bound_hash_mismatch(migrated_engine, parents) -> None:
    _failed(
        migrated_engine,
        insert(prediction_jobs).values(
            **_job_values(parents, input_snapshot_hash="b" * 64),
        ),
    )


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


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_m1_plus_count_24h": float("inf")},
        {"activity_radius_median_km_24h": float("inf")},
        {
            "maximum_magnitude_q05_24h": 1.0,
            "maximum_magnitude_q50_24h": 2.0,
            "maximum_magnitude_q95_24h": float("inf"),
        },
    ],
)
def test_forecasts_reject_nonfinite_outputs(migrated_engine, parents, changes) -> None:
    job = _job_values(parents)
    with migrated_engine.begin() as connection:
        connection.execute(insert(prediction_jobs).values(**job))
    _failed(migrated_engine, insert(forecasts).values(**_forecast_values(job["job_id"], **changes)))


def test_one_alert_job_is_allowed_per_forecast(migrated_engine, parents) -> None:
    job = _job_values(parents)
    forecast = _forecast_values(job["job_id"])
    first_alert = {
        "alert_job_id": uuid4(),
        "forecast_id": forecast["forecast_id"],
        "requested_at": NOW,
        "message_snapshot": "Automatic earthquake alert",
        "recipient_policy_snapshot": {"version": "1"},
        "expires_at": NOW + timedelta(hours=24),
        "correlation_id": uuid4(),
    }
    with migrated_engine.begin() as connection:
        connection.execute(insert(prediction_jobs).values(**job))
        connection.execute(insert(forecasts).values(**forecast))
        connection.execute(insert(alert_jobs).values(**first_alert))

    _failed(
        migrated_engine,
        insert(alert_jobs).values(
            alert_job_id=uuid4(),
            forecast_id=forecast["forecast_id"],
            requested_at=NOW,
            message_snapshot="Duplicate automatic earthquake alert",
            recipient_policy_snapshot={"version": "1"},
            expires_at=NOW + timedelta(hours=24),
            correlation_id=uuid4(),
        ),
    )


def test_alert_snapshots_cannot_change_after_creation(migrated_engine, parents) -> None:
    job = _job_values(parents)
    forecast = _forecast_values(job["job_id"])
    alert_id = uuid4()
    alert = {
        "alert_job_id": alert_id,
        "forecast_id": forecast["forecast_id"],
        "requested_at": NOW,
        "message_snapshot": "Automatic earthquake alert",
        "recipient_policy_snapshot": {"version": "1"},
        "expires_at": NOW + timedelta(hours=24),
        "correlation_id": uuid4(),
    }
    with migrated_engine.begin() as connection:
        connection.execute(insert(prediction_jobs).values(**job))
        connection.execute(insert(forecasts).values(**forecast))

    _failed(
        migrated_engine,
        insert(alert_jobs).values(**{**alert, "recipient_policy_snapshot": ["invalid"]}),
    )
    with migrated_engine.begin() as connection:
        connection.execute(insert(alert_jobs).values(**alert))

    for changes in (
        {"message_snapshot": "Changed alert"},
        {"recipient_policy_snapshot": {"version": "2"}},
    ):
        _failed(
            migrated_engine,
            update(alert_jobs).where(alert_jobs.c.alert_job_id == alert_id).values(**changes),
        )

    with migrated_engine.begin() as connection:
        connection.execute(
            update(alert_jobs)
            .where(alert_jobs.c.alert_job_id == alert_id)
            .values(status="failed", completed_at=NOW)
        )
        stored = connection.execute(
            select(alert_jobs).where(alert_jobs.c.alert_job_id == alert_id)
        ).one()
    assert stored.status == "failed"
    assert stored.message_snapshot == alert["message_snapshot"]
    assert stored.recipient_policy_snapshot == alert["recipient_policy_snapshot"]


def test_forecast_cannot_supersede_itself(migrated_engine, parents) -> None:
    job = _job_values(parents)
    forecast = _forecast_values(job["job_id"])
    forecast["supersedes_forecast_id"] = forecast["forecast_id"]
    with migrated_engine.begin() as connection:
        connection.execute(insert(prediction_jobs).values(**job))
    _failed(migrated_engine, insert(forecasts).values(**forecast))


def test_forecast_cannot_supersede_a_different_event(migrated_engine, parents) -> None:
    first_job = _job_values(parents)
    first_forecast = _forecast_values(first_job["job_id"])
    other_event_id = uuid4()
    other_revision_id = uuid4()
    other_job = _job_values(parents, event_revision_id=other_revision_id)
    with migrated_engine.begin() as connection:
        connection.execute(insert(prediction_jobs).values(**first_job))
        connection.execute(insert(forecasts).values(**first_forecast))
        connection.execute(
            insert(earthquake_events).values(
                event_id=other_event_id,
                first_seen_run_id=parents["run"],
                last_seen_run_id=parents["run"],
            )
        )
        connection.execute(
            insert(earthquake_bulletin_event_identities).values(
                source_bulletin_id="2026_0831_1610_B1",
                event_id=other_event_id,
            )
        )
        connection.execute(
            insert(earthquake_event_revisions).values(
                **_revision_values(
                    parents,
                    event_revision_id=other_revision_id,
                    event_id=other_event_id,
                    revision_number=1,
                    source_bulletin_id="2026_0831_1610_B1",
                    source_event_group_id="2026_0831_1610",
                )
            )
        )
        connection.execute(insert(prediction_jobs).values(**other_job))

    _failed(
        migrated_engine,
        insert(forecasts).values(
            **_forecast_values(
                other_job["job_id"], supersedes_forecast_id=first_forecast["forecast_id"]
            )
        ),
    )


def test_forecast_supersession_cannot_form_a_cycle(migrated_engine, parents) -> None:
    first_job = _job_values(parents)
    first_forecast = _forecast_values(first_job["job_id"])
    later_revision = _revision_values(parents)
    later_job = _job_values(parents, event_revision_id=later_revision["event_revision_id"])
    later_forecast = _forecast_values(
        later_job["job_id"], supersedes_forecast_id=first_forecast["forecast_id"]
    )
    with migrated_engine.begin() as connection:
        connection.execute(insert(prediction_jobs).values(**first_job))
        connection.execute(insert(forecasts).values(**first_forecast))
        connection.execute(
            insert(earthquake_bulletin_event_identities).values(
                source_bulletin_id=later_revision["source_bulletin_id"],
                event_id=parents["event"],
            )
        )
        connection.execute(insert(earthquake_event_revisions).values(**later_revision))
        connection.execute(insert(prediction_jobs).values(**later_job))
        connection.execute(insert(forecasts).values(**later_forecast))

    _failed(
        migrated_engine,
        update(forecasts)
        .where(forecasts.c.forecast_id == first_forecast["forecast_id"])
        .values(supersedes_forecast_id=later_forecast["forecast_id"]),
    )


def test_forecast_cannot_be_changed_after_creation(migrated_engine, parents) -> None:
    job = _job_values(parents)
    forecast = _forecast_values(job["job_id"])
    with migrated_engine.begin() as connection:
        connection.execute(insert(prediction_jobs).values(**job))
        connection.execute(insert(forecasts).values(**forecast))

    _failed(
        migrated_engine,
        update(forecasts)
        .where(forecasts.c.forecast_id == forecast["forecast_id"])
        .values(expected_m1_plus_count_24h=3.0),
    )
    with migrated_engine.begin() as connection:
        stored_count = connection.execute(
            select(forecasts.c.expected_m1_plus_count_24h).where(
                forecasts.c.forecast_id == forecast["forecast_id"]
            )
        ).scalar_one()
    assert stored_count == forecast["expected_m1_plus_count_24h"]


def test_user_audit_actor_is_deferred_until_users_exist(migrated_engine) -> None:
    _failed(
        migrated_engine,
        insert(audit_logs).values(
            audit_id=uuid4(),
            actor_type="user",
            actor_user_id=uuid4(),
            action="unsupported_user_action",
            outcome="succeeded",
            correlation_id=uuid4(),
        ),
    )


def test_system_audit_actor_remains_available(migrated_engine) -> None:
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(audit_logs).values(
                audit_id=uuid4(),
                actor_type="system",
                actor_service="prediction-worker",
                action="forecast_completed",
                outcome="succeeded",
                correlation_id=uuid4(),
            )
        )


@pytest.mark.parametrize("metadata_value", [["invalid"], "invalid", 7, None])
def test_audit_metadata_must_be_an_object(migrated_engine, metadata_value) -> None:
    _failed(
        migrated_engine,
        insert(audit_logs).values(
            audit_id=uuid4(),
            actor_type="system",
            actor_service="prediction-worker",
            action="forecast_completed",
            outcome="succeeded",
            correlation_id=uuid4(),
            metadata=metadata_value,
        ),
    )

    with migrated_engine.begin() as connection:
        connection.execute(
            insert(audit_logs).values(
                audit_id=uuid4(),
                actor_type="system",
                actor_service="prediction-worker",
                action="forecast_completed",
                outcome="succeeded",
                correlation_id=uuid4(),
                metadata={"model_release": "SEIS 1.0.1"},
            )
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_service": " "},
        {"action": " "},
        {"target_type": " ", "target_id": "forecast"},
        {"target_type": "forecast", "target_id": " "},
        {"target_revision": " "},
        {"reason_code": " "},
    ],
)
def test_audit_identifiers_and_codes_cannot_be_blank(migrated_engine, changes) -> None:
    _failed(
        migrated_engine,
        insert(audit_logs).values(
            **{
                "audit_id": uuid4(),
                "actor_type": "system",
                "actor_service": "prediction-worker",
                "action": "forecast_completed",
                "outcome": "succeeded",
                "correlation_id": uuid4(),
                **changes,
            }
        ),
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


def test_ingestion_and_dispatch_indexes_exist(migrated_engine) -> None:
    run_indexes = {item["name"] for item in inspect(migrated_engine).get_indexes("ingestion_runs")}
    input_indexes = {
        item["name"] for item in inspect(migrated_engine).get_indexes("ingestion_run_inputs")
    }
    dispatch_indexes = {
        item["name"] for item in inspect(migrated_engine).get_indexes("job_dispatches")
    }
    assert "uq_ingestion_runs_one_active" in run_indexes
    assert "ix_ingestion_runs_running_lease" in run_indexes
    assert "ix_ingestion_run_inputs_event_id" in input_indexes
    assert {"ix_job_dispatches_ready", "ix_job_dispatches_dispatching_lease"} <= dispatch_indexes
