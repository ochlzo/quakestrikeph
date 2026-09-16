from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import DataError, IntegrityError

from quakestrike.application.persistence import (
    EventRevisionRequest,
    EventTransactionRequest,
    PredictionWorkRequest,
    RunDispatchRequest,
)
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

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 16, tzinfo=UTC)


def _transactions(engine) -> SqlAlchemyIngestionTransactions:
    return SqlAlchemyIngestionTransactions(create_session_factory(engine))


def test_overlapping_active_run_requests_return_one_run_and_dispatch(migrated_engine) -> None:
    transactions = _transactions(migrated_engine)
    requests = [
        RunDispatchRequest(
            run_id=uuid4(),
            dispatch_id=uuid4(),
            trigger_type="scheduled",
            correlation_id=uuid4(),
        )
        for _ in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(transactions.create_run_with_dispatch, requests))

    assert {result.run_id for result in results} == {results[0].run_id}
    assert {result.dispatch_id for result in results} == {results[0].dispatch_id}
    assert sorted(result.created for result in results) == [False, True]
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ingestion_runs)) == 1
        assert connection.scalar(select(func.count()).select_from(job_dispatches)) == 1


def test_run_and_dispatch_failure_rolls_back_run(migrated_engine) -> None:
    request = RunDispatchRequest(
        run_id=uuid4(),
        dispatch_id="not-a-uuid",  # type: ignore[arg-type]
        trigger_type="manual",
        correlation_id=uuid4(),
    )
    with pytest.raises(DataError):
        _transactions(migrated_engine).create_run_with_dispatch(request)
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ingestion_runs)) == 0


def _revision(run_id):
    return EventRevisionRequest(
        event_revision_id=uuid4(),
        ingestion_run_id=run_id,
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


def test_event_revision_prediction_and_dispatch_commit_together(migrated_engine) -> None:
    run_id = uuid4()
    release_id = uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(ingestion_runs).values(
                run_id=run_id,
                trigger_type="backfill",
                status="succeeded",
                started_at=NOW,
                finished_at=NOW,
                correlation_id=uuid4(),
            )
        )
        connection.execute(
            insert(model_releases).values(
                model_release_id=release_id,
                version_label="SEIS 1.0",
                artifact_manifest_uri="model-artifacts/manifest.json",
                artifact_manifest_hash="a" * 64,
                input_schema_version="1",
                output_schema_version="1",
            )
        )
    revision = _revision(run_id)
    prediction = PredictionWorkRequest(
        job_id=uuid4(),
        dispatch_id=uuid4(),
        model_release_id=release_id,
        input_snapshot_hash="b" * 64,
        input_snapshot_json={"anchor_magnitude": 4.2},
        idempotency_key=str(uuid4()),
        correlation_id=uuid4(),
    )
    _transactions(migrated_engine).process_event(
        EventTransactionRequest(
            event_id=uuid4(),
            ingestion_run_id=run_id,
            revision=revision,
            prediction=prediction,
        )
    )
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(earthquake_events)) == 1
        assert connection.scalar(select(func.count()).select_from(earthquake_event_revisions)) == 1
        assert connection.scalar(select(func.count()).select_from(prediction_jobs)) == 1
        assert connection.scalar(select(func.count()).select_from(job_dispatches)) == 1


def test_event_transaction_failure_rolls_back_event_and_revision(migrated_engine) -> None:
    run_id = uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(ingestion_runs).values(
                run_id=run_id,
                trigger_type="backfill",
                status="succeeded",
                started_at=NOW,
                finished_at=NOW,
                correlation_id=uuid4(),
            )
        )
    revision = _revision(run_id)
    prediction = PredictionWorkRequest(
        job_id=uuid4(),
        dispatch_id=uuid4(),
        model_release_id=uuid4(),
        input_snapshot_hash="c" * 64,
        input_snapshot_json={"anchor_magnitude": 4.2},
        idempotency_key=str(uuid4()),
        correlation_id=uuid4(),
    )
    with pytest.raises(IntegrityError):
        _transactions(migrated_engine).process_event(
            EventTransactionRequest(
                event_id=uuid4(),
                ingestion_run_id=run_id,
                revision=revision,
                prediction=prediction,
            )
        )
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(earthquake_events)) == 0
        assert connection.scalar(select(func.count()).select_from(earthquake_event_revisions)) == 0
        assert connection.scalar(select(func.count()).select_from(prediction_jobs)) == 0
        assert connection.scalar(select(func.count()).select_from(job_dispatches)) == 0


def _seed_run_and_release(engine):
    run_id = uuid4()
    release_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(ingestion_runs).values(
                run_id=run_id,
                trigger_type="backfill",
                status="succeeded",
                started_at=NOW,
                finished_at=NOW,
                correlation_id=uuid4(),
            )
        )
        connection.execute(
            insert(model_releases).values(
                model_release_id=release_id,
                version_label="SEIS 1.0",
                artifact_manifest_uri="model-artifacts/manifest.json",
                artifact_manifest_hash="a" * 64,
                input_schema_version="1",
                output_schema_version="1",
            )
        )
    return run_id, release_id


def _event_request(run_id, release_id, *, event_id=None, revision=None, prediction=None):
    revision = revision or _revision(run_id)
    prediction = prediction or PredictionWorkRequest(
        job_id=uuid4(),
        dispatch_id=uuid4(),
        model_release_id=release_id,
        input_snapshot_hash="b" * 64,
        input_snapshot_json={"anchor_magnitude": 4.2},
        idempotency_key=str(uuid4()),
        correlation_id=uuid4(),
    )
    return EventTransactionRequest(
        event_id=event_id or uuid4(),
        ingestion_run_id=run_id,
        revision=revision,
        prediction=prediction,
    )


def test_duplicate_event_delivery_reuses_original_work(migrated_engine) -> None:
    run_id, release_id = _seed_run_and_release(migrated_engine)
    transactions = _transactions(migrated_engine)
    first_request = _event_request(run_id, release_id)
    first = transactions.process_event(first_request)
    replay = replace(
        first_request,
        revision=replace(first_request.revision, event_revision_id=uuid4()),
        prediction=replace(
            first_request.prediction,
            job_id=uuid4(),
            dispatch_id=uuid4(),
            idempotency_key=str(uuid4()),
        ),
    )
    second = transactions.process_event(replay)

    assert second.event_revision_id == first.event_revision_id
    assert second.prediction_job_id == first.prediction_job_id
    assert second.dispatch_id == first.dispatch_id
    assert second.revision_created is False
    assert second.prediction_created is False
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(earthquake_events)) == 1
        assert connection.scalar(select(func.count()).select_from(earthquake_event_revisions)) == 1
        assert connection.scalar(select(func.count()).select_from(prediction_jobs)) == 1
        assert connection.scalar(select(func.count()).select_from(job_dispatches)) == 1


def test_group_only_event_delivery_reuses_original_revision(migrated_engine) -> None:
    run_id, release_id = _seed_run_and_release(migrated_engine)
    transactions = _transactions(migrated_engine)
    group_only_revision = replace(_revision(run_id), source_bulletin_id=None)
    first_request = _event_request(run_id, release_id, revision=group_only_revision)
    first = transactions.process_event(first_request)

    replay = replace(
        first_request,
        revision=replace(group_only_revision, event_revision_id=uuid4()),
        prediction=replace(
            first_request.prediction,
            job_id=uuid4(),
            dispatch_id=uuid4(),
            idempotency_key=str(uuid4()),
        ),
    )
    second = transactions.process_event(replay)

    assert second.event_revision_id == first.event_revision_id
    assert second.revision_number == first.revision_number
    assert second.prediction_job_id == first.prediction_job_id
    assert second.dispatch_id == first.dispatch_id
    assert second.revision_created is False
    assert second.prediction_created is False
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(earthquake_event_revisions)) == 1
        assert connection.scalar(select(func.count()).select_from(prediction_jobs)) == 1
        assert connection.scalar(select(func.count()).select_from(job_dispatches)) == 1


def test_revision_identity_collision_rolls_back_observation(migrated_engine) -> None:
    run_id, release_id = _seed_run_and_release(migrated_engine)
    transactions = _transactions(migrated_engine)
    request = _event_request(run_id, release_id)
    transactions.process_event(request)
    with migrated_engine.connect() as connection:
        before = connection.execute(
            select(earthquake_events.c.last_seen_run_id, earthquake_events.c.updated_at)
        ).one()
    conflicting = replace(
        request,
        revision=replace(request.revision, magnitude=Decimal("9.99")),
    )
    with pytest.raises(ValueError, match="different content"):
        transactions.process_event(conflicting)
    with migrated_engine.connect() as connection:
        after = connection.execute(
            select(earthquake_events.c.last_seen_run_id, earthquake_events.c.updated_at)
        ).one()
        assert after == before
        assert connection.scalar(select(func.count()).select_from(earthquake_event_revisions)) == 1


def test_supplied_prediction_identity_collision_rolls_back(migrated_engine) -> None:
    run_id, release_id = _seed_run_and_release(migrated_engine)
    transactions = _transactions(migrated_engine)
    original = _event_request(run_id, release_id)
    transactions.process_event(original)
    conflicting_revision = replace(
        _revision(run_id),
        source_bulletin_id="2026_0831_1609_B2",
        source_url="https://earthquake.phivolcs.dost.gov.ph/example-b2",
    )
    conflicting_prediction = replace(
        original.prediction,
        dispatch_id=uuid4(),
        input_snapshot_hash="c" * 64,
    )
    with pytest.raises(ValueError, match="job ID"):
        transactions.process_event(
            _event_request(
                run_id,
                release_id,
                event_id=original.event_id,
                revision=conflicting_revision,
                prediction=conflicting_prediction,
            )
        )
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(earthquake_event_revisions)) == 1


def test_concurrent_event_revisions_are_serial_and_duplicate_safe(migrated_engine) -> None:
    run_id, release_id = _seed_run_and_release(migrated_engine)
    transactions = _transactions(migrated_engine)
    event_id = uuid4()
    first_revision = _revision(run_id)
    changed_revision = replace(
        _revision(run_id),
        source_bulletin_id="2026_0831_1609_B2",
        source_url="https://earthquake.phivolcs.dost.gov.ph/example-b2",
        magnitude=Decimal("4.30"),
    )
    requests = [
        _event_request(run_id, release_id, event_id=event_id, revision=first_revision),
        _event_request(
            run_id,
            release_id,
            event_id=event_id,
            revision=changed_revision,
            prediction=PredictionWorkRequest(
                job_id=uuid4(),
                dispatch_id=uuid4(),
                model_release_id=release_id,
                input_snapshot_hash="c" * 64,
                input_snapshot_json={"anchor_magnitude": 4.3},
                idempotency_key=str(uuid4()),
                correlation_id=uuid4(),
            ),
        ),
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(transactions.process_event, requests))
    assert sorted(result.revision_number for result in results) == [1, 2]
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(earthquake_events)) == 1

    duplicate_requests = [
        _event_request(
            run_id,
            release_id,
            event_id=event_id,
            revision=replace(first_revision, event_revision_id=uuid4()),
        )
        for _ in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(transactions.process_event, duplicate_requests))
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(earthquake_event_revisions)) == 2


def test_later_observation_refreshes_event_timestamp(migrated_engine) -> None:
    run_id, release_id = _seed_run_and_release(migrated_engine)
    transactions = _transactions(migrated_engine)
    request = _event_request(run_id, release_id)
    transactions.process_event(request)
    old = NOW - timedelta(days=1)
    later_run = uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            update(earthquake_events)
            .where(earthquake_events.c.event_id == request.event_id)
            .values(updated_at=old)
        )
        connection.execute(
            insert(ingestion_runs).values(
                run_id=later_run,
                trigger_type="backfill",
                status="succeeded",
                started_at=NOW,
                finished_at=NOW,
                correlation_id=uuid4(),
            )
        )
    transactions.process_event(
        EventTransactionRequest(event_id=request.event_id, ingestion_run_id=later_run)
    )
    with migrated_engine.connect() as connection:
        row = connection.execute(select(earthquake_events)).one()
    assert row.last_seen_run_id == later_run
    assert row.updated_at > old
