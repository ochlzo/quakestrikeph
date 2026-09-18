from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from kombu import Connection
from redis import Redis
from sqlalchemy import func, insert, select

from quakestrike.application.dispatch import DispatchClaimLost, DurableDispatcher
from quakestrike.application.persistence import (
    EventRevisionRequest,
    EventTransactionRequest,
    FeatureEventTransactionRequest,
    PredictionWorkRequest,
)
from quakestrike.domain.features import (
    INPUT_SCHEMA_VERSION,
    HistoryCoverage,
    feature_snapshot_hash,
)
from quakestrike.infrastructure.database.dispatch import SqlAlchemyDispatchStore
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.feature_history import (
    SqlAlchemyFeatureHistoryQuery,
    observation_from_revision_request,
)
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.database.tables import (
    earthquake_event_revisions,
    earthquake_events,
    ingestion_runs,
    job_dispatches,
    model_releases,
    prediction_jobs,
)
from quakestrike.infrastructure.queues.celery_app import (
    PREDICTION_QUEUE,
    create_celery_app,
)
from quakestrike.infrastructure.queues.ingestion_publisher import CeleryIngestionPublisher
from quakestrike.infrastructure.queues.prediction_publisher import (
    PREDICTION_TASK_NAME,
    CeleryPredictionPublisher,
)
from quakestrike.infrastructure.settings import Settings

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


class VerifiedReleaseGate:
    def __init__(self, release_id):
        self.release_id = release_id

    def is_verified(self, release_id) -> bool:
        return release_id == self.release_id


def _transactions(engine, release_id=None) -> SqlAlchemyIngestionTransactions:
    return SqlAlchemyIngestionTransactions(
        create_session_factory(engine),
        model_release_verifier=VerifiedReleaseGate(release_id),
    )


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
                artifact_manifest_uri="model-artifacts/seis-1.0/manifest.json",
                artifact_manifest_hash="a" * 64,
                input_schema_version=INPUT_SCHEMA_VERSION,
                output_schema_version="quakestrike.prediction-output.v1",
            )
        )
    return run_id, release_id


def _revision(
    run_id,
    *,
    event_time: datetime,
    bulletin_id: str,
    event_group_id: str | None = None,
    magnitude: str = "2.00",
    latitude: str = "14.000000",
    longitude: str = "121.000000",
    precision: str = "second",
    source_url: str | None = None,
) -> EventRevisionRequest:
    return EventRevisionRequest(
        event_revision_id=uuid4(),
        ingestion_run_id=run_id,
        source_bulletin_id=bulletin_id,
        source_event_group_id=event_group_id or bulletin_id.removesuffix("_B1"),
        source_url=source_url or f"https://earthquake.phivolcs.dost.gov.ph/{bulletin_id}",
        source_time_precision=precision,
        event_time=event_time,
        latitude=Decimal(latitude),
        longitude=Decimal(longitude),
        depth_km=Decimal("10.000"),
        magnitude=Decimal(magnitude),
        location_description="Example location",
    )


def _insert_history_event(engine, run_id, revision: EventRevisionRequest):
    event_id = uuid4()
    _transactions(engine).process_event(
        EventTransactionRequest(
            event_id=event_id,
            ingestion_run_id=run_id,
            revision=revision,
        )
    )
    return event_id


def _feature_request(run_id, release_id, *, event_id=None, revision=None, coverage=None):
    revision = revision or _revision(
        run_id,
        event_time=NOW,
        bulletin_id="2026_0916_1200_B1",
        magnitude="4.20",
        precision="minute",
    )
    return FeatureEventTransactionRequest(
        event_id=event_id or uuid4(),
        ingestion_run_id=run_id,
        revision=revision,
        model_release_id=release_id,
        correlation_id=uuid4(),
        history_coverage=coverage
        if coverage is not None
        else HistoryCoverage(NOW - timedelta(days=7), NOW, True),
    )


def _counts(engine):
    with engine.connect() as connection:
        return {
            "events": connection.scalar(select(func.count()).select_from(earthquake_events)),
            "revisions": connection.scalar(
                select(func.count()).select_from(earthquake_event_revisions)
            ),
            "jobs": connection.scalar(select(func.count()).select_from(prediction_jobs)),
            "dispatches": connection.scalar(select(func.count()).select_from(job_dispatches)),
        }


def test_below_m1_and_incomplete_history_retain_revisions_without_prediction_work(
    migrated_engine,
) -> None:
    run_id, release_id = _seed_run_and_release(migrated_engine)
    transactions = _transactions(migrated_engine)

    below_m1 = _feature_request(
        run_id,
        release_id,
        revision=_revision(
            run_id,
            event_time=NOW,
            bulletin_id="2026_0916_1200_B1",
            magnitude="0.99",
        ),
        coverage=None,
    )
    below_result = transactions.process_event_with_features(below_m1)

    incomplete = _feature_request(
        run_id,
        release_id,
        revision=_revision(
            run_id,
            event_time=NOW + timedelta(minutes=1),
            bulletin_id="2026_0916_1201_B1",
            magnitude="1.00",
        ),
        coverage=HistoryCoverage(NOW - timedelta(days=6), NOW + timedelta(minutes=1), True),
    )
    incomplete_result = transactions.process_event_with_features(incomplete)

    assert below_result.prediction_job_id is None
    assert below_result.prediction_skip_reason == "magnitude_below_m1"
    assert incomplete_result.prediction_job_id is None
    assert incomplete_result.prediction_skip_reason == "history_starts_after_required_window"
    assert _counts(migrated_engine) == {"events": 2, "revisions": 2, "jobs": 0, "dispatches": 0}
    with migrated_engine.connect() as connection:
        reasons = (
            connection.execute(
                select(earthquake_event_revisions.c.prediction_skip_reason).order_by(
                    earthquake_event_revisions.c.event_time
                )
            )
            .scalars()
            .all()
        )
    assert reasons == ["magnitude_below_m1", "history_starts_after_required_window"]


def test_custom_incomplete_history_reason_is_mapped_and_revision_is_retained(
    migrated_engine,
) -> None:
    run_id, release_id = _seed_run_and_release(migrated_engine)
    request = _feature_request(
        run_id,
        release_id,
        coverage=HistoryCoverage(
            NOW - timedelta(days=7),
            NOW,
            False,
            reason="source_feed_gap",
        ),
    )

    result = _transactions(migrated_engine).process_event_with_features(request)

    assert result.prediction_created is False
    assert result.prediction_skip_reason == "incomplete_feature_history"
    assert _counts(migrated_engine) == {"events": 1, "revisions": 1, "jobs": 0, "dispatches": 0}


def test_unconfigured_schema_compatible_release_cannot_create_prediction_work(
    migrated_engine,
) -> None:
    run_id, configured_release_id = _seed_run_and_release(migrated_engine)
    other_release_id = uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(model_releases).values(
                model_release_id=other_release_id,
                version_label="SEIS 2.0",
                artifact_manifest_uri="model-artifacts/seis-2.0/manifest.json",
                artifact_manifest_hash="b" * 64,
                input_schema_version=INPUT_SCHEMA_VERSION,
                output_schema_version="quakestrike.prediction-output.v1",
            )
        )
    _insert_history_event(
        migrated_engine,
        run_id,
        _revision(
            run_id,
            event_time=NOW - timedelta(hours=1),
            bulletin_id="2026_0916_1100_B1",
        ),
    )

    class VerifiedReleaseGate:
        def is_verified(self, release_id) -> bool:
            return release_id == configured_release_id

    transactions = SqlAlchemyIngestionTransactions(
        create_session_factory(migrated_engine),
        model_release_verifier=VerifiedReleaseGate(),
    )
    result = transactions.process_event_with_features(_feature_request(run_id, other_release_id))

    assert result.prediction_created is False
    assert result.prediction_skip_reason == "model_release_unavailable"
    assert _counts(migrated_engine) == {"events": 2, "revisions": 2, "jobs": 0, "dispatches": 0}


def test_generic_prediction_work_for_an_unverified_release_retains_the_revision(
    migrated_engine,
) -> None:
    run_id, release_id = _seed_run_and_release(migrated_engine)

    class RejectedReleaseGate:
        def is_verified(self, release_id) -> bool:
            return False

    revision = _revision(
        run_id,
        event_time=NOW,
        bulletin_id="2026_0916_1200_B1",
    )
    snapshot = {
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
    request = EventTransactionRequest(
        event_id=uuid4(),
        ingestion_run_id=run_id,
        revision=revision,
        prediction=PredictionWorkRequest(
            job_id=uuid4(),
            dispatch_id=uuid4(),
            model_release_id=release_id,
            input_snapshot_hash=feature_snapshot_hash(snapshot),
            input_snapshot_json=snapshot,
            idempotency_key=str(uuid4()),
            correlation_id=uuid4(),
        ),
    )

    result = SqlAlchemyIngestionTransactions(
        create_session_factory(migrated_engine),
        model_release_verifier=RejectedReleaseGate(),
    ).process_event(request)

    assert result.prediction_created is False
    assert result.prediction_skip_reason == "model_release_unavailable"
    assert _counts(migrated_engine) == {"events": 1, "revisions": 1, "jobs": 0, "dispatches": 0}


def test_prior_history_query_excludes_observations_at_the_anchor_timestamp(
    migrated_engine,
) -> None:
    run_id, _ = _seed_run_and_release(migrated_engine)
    earlier_event_id = _insert_history_event(
        migrated_engine,
        run_id,
        _revision(
            run_id,
            event_time=NOW - timedelta(seconds=1),
            bulletin_id="2026_0916_115959_B1",
        ),
    )
    same_time_event_id = _insert_history_event(
        migrated_engine,
        run_id,
        _revision(
            run_id,
            event_time=NOW,
            bulletin_id="2026_0916_120000_B1",
        ),
    )
    anchor = observation_from_revision_request(
        uuid4(),
        _revision(
            run_id,
            event_time=NOW,
            bulletin_id="2026_0916_120000_B2",
        ),
    )

    selection = SqlAlchemyFeatureHistoryQuery(
        create_session_factory(migrated_engine)
    ).select_prior_history(anchor)

    assert {observation.event_id for observation in selection.observations} == {earlier_event_id}
    assert same_time_event_id not in {
        observation.event_id for observation in selection.observations
    }


def test_eligible_revision_stores_complete_snapshot_and_prediction_dispatch(
    migrated_engine,
) -> None:
    run_id, release_id = _seed_run_and_release(migrated_engine)
    _insert_history_event(
        migrated_engine,
        run_id,
        _revision(
            run_id,
            event_time=NOW - timedelta(days=7),
            bulletin_id="2026_0909_1200_B1",
            precision="second",
        ),
    )
    result = _transactions(migrated_engine, release_id).process_event_with_features(
        _feature_request(run_id, release_id)
    )

    assert result.prediction_created is True
    assert result.prediction_skip_reason is None
    with migrated_engine.connect() as connection:
        job = connection.execute(select(prediction_jobs)).one()
        dispatch = connection.execute(select(job_dispatches)).one()

    assert set(job.input_snapshot_json) == {
        "anchor_magnitude",
        "anchor_depth_km",
        "anchor_latitude",
        "anchor_longitude",
        "anchor_time_is_minute_precision",
        "catalog_m1_plus_count_past_1h",
        "catalog_m1_plus_count_past_24h",
        "catalog_m1_plus_count_past_7d",
        "local_m1_plus_count_past_24h_within_50km",
        "local_m1_plus_count_past_24h_within_100km",
    }
    assert job.input_snapshot_json["catalog_m1_plus_count_past_7d"] == 1
    assert job.input_snapshot_hash == feature_snapshot_hash(
        job.input_snapshot_json,
        INPUT_SCHEMA_VERSION,
    )
    assert dispatch.prediction_job_id == job.job_id
    assert result.dispatch_id == dispatch.dispatch_id


def test_missing_model_release_retains_revision_without_prediction_work(migrated_engine) -> None:
    run_id, _ = _seed_run_and_release(migrated_engine)
    request = _feature_request(run_id, uuid4())

    result = _transactions(migrated_engine).process_event_with_features(request)

    assert result.prediction_created is False
    assert result.prediction_skip_reason == "model_release_unavailable"
    assert _counts(migrated_engine) == {"events": 1, "revisions": 1, "jobs": 0, "dispatches": 0}


class FailingPublisher:
    def publish(self, dispatch) -> None:
        raise RuntimeError("Redis is unavailable")


def test_publish_failure_after_commit_leaves_durable_prediction_work(migrated_engine) -> None:
    run_id, release_id = _seed_run_and_release(migrated_engine)
    _insert_history_event(
        migrated_engine,
        run_id,
        _revision(
            run_id,
            event_time=NOW - timedelta(hours=1),
            bulletin_id="2026_0916_1100_B1",
        ),
    )

    result = _transactions(migrated_engine, release_id).process_event_with_features(
        _feature_request(run_id, release_id)
    )
    dispatch_result = DurableDispatcher(
        SqlAlchemyDispatchStore(create_session_factory(migrated_engine)),
        {"ingestion": FailingPublisher(), "prediction": FailingPublisher()},
        batch_size=10,
    ).dispatch_due()

    assert result.prediction_created is True
    assert dispatch_result.retry_wait == 1
    assert _counts(migrated_engine) == {"events": 2, "revisions": 2, "jobs": 1, "dispatches": 1}
    with migrated_engine.connect() as connection:
        dispatch = connection.execute(select(job_dispatches)).one()
    assert dispatch.status == "retry_wait"
    assert dispatch.next_dispatch_at is not None
    assert dispatch.lease_expires_at is None
    assert dispatch.dispatch_token is None
    assert dispatch.last_error == "RuntimeError"


class RecordingPublisher:
    def __init__(self) -> None:
        self.messages = []

    def publish(self, dispatch) -> None:
        self.messages.append(dispatch)


def test_successful_prediction_publication_records_enqueued_state(migrated_engine) -> None:
    run_id, release_id = _seed_run_and_release(migrated_engine)
    _insert_history_event(
        migrated_engine,
        run_id,
        _revision(
            run_id,
            event_time=NOW - timedelta(hours=1),
            bulletin_id="2026_0916_1100_B1",
        ),
    )
    publisher = RecordingPublisher()

    result = _transactions(migrated_engine, release_id).process_event_with_features(
        _feature_request(run_id, release_id)
    )
    dispatch_result = DurableDispatcher(
        SqlAlchemyDispatchStore(create_session_factory(migrated_engine)),
        {"ingestion": publisher, "prediction": publisher},
        batch_size=10,
    ).dispatch_due()

    assert result.prediction_created is True
    assert dispatch_result.enqueued == 1
    assert len(publisher.messages) == 1
    with migrated_engine.connect() as connection:
        dispatch = connection.execute(select(job_dispatches)).one()
    assert dispatch.status == "enqueued"
    assert dispatch.last_dispatched_at is not None
    assert dispatch.next_dispatch_at is None
    assert dispatch.lease_expires_at is None
    assert dispatch.dispatch_token is None


def test_ingestion_transaction_reaches_real_prediction_queue(migrated_engine) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    redis_url = os.environ.get("TEST_REDIS_URL")
    if database_url is None or redis_url is None:
        pytest.skip("TEST_DATABASE_URL and TEST_REDIS_URL are required for this integration test.")

    redis_client = Redis.from_url(redis_url)
    redis_client.delete(PREDICTION_QUEUE)
    try:
        run_id, release_id = _seed_run_and_release(migrated_engine)
        _insert_history_event(
            migrated_engine,
            run_id,
            _revision(
                run_id,
                event_time=NOW - timedelta(hours=1),
                bulletin_id="2026_0916_1100_B1",
            ),
        )
        settings = Settings(
            _env_file=None,
            database_url=database_url,
            redis_url=redis_url,
            phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
            model_release_id=release_id,
        )
        app = create_celery_app(settings)
        transactions = _transactions(migrated_engine, release_id)
        request = _feature_request(run_id, release_id)
        result = transactions.process_event_with_features(request)
        dispatch_result = DurableDispatcher(
            SqlAlchemyDispatchStore(create_session_factory(migrated_engine)),
            {
                "ingestion": CeleryIngestionPublisher(app),
                "prediction": CeleryPredictionPublisher(app),
            },
            batch_size=10,
        ).dispatch_due()

        assert result.prediction_created is True
        assert dispatch_result.enqueued == 1
        with Connection(redis_url) as connection:
            queue = connection.SimpleQueue(PREDICTION_QUEUE)
            message = queue.get(block=False)
            try:
                assert message.headers["task"] == PREDICTION_TASK_NAME
                assert message.delivery_info["routing_key"] == PREDICTION_QUEUE
                payload = message.payload[0][0]
                assert payload == {
                    "message_version": 1,
                    "dispatch_id": str(result.dispatch_id),
                    "job_id": str(result.prediction_job_id),
                    "correlation_id": str(request.correlation_id),
                }
            finally:
                message.ack()
                queue.close()
    finally:
        redis_client.delete(PREDICTION_QUEUE)
        redis_client.close()


def test_prediction_dispatch_reclaims_expired_claim_and_fences_old_token(
    migrated_engine,
) -> None:
    run_id, release_id = _seed_run_and_release(migrated_engine)
    _insert_history_event(
        migrated_engine,
        run_id,
        _revision(
            run_id,
            event_time=NOW - timedelta(hours=1),
            bulletin_id="2026_0916_1100_B1",
        ),
    )
    _transactions(migrated_engine, release_id).process_event_with_features(
        _feature_request(run_id, release_id)
    )
    with migrated_engine.connect() as connection:
        database_now = connection.scalar(select(func.now()))

    store = SqlAlchemyDispatchStore(
        create_session_factory(migrated_engine),
        clock=lambda: database_now,
    )
    original = store.claim_due(1, now=database_now)[0]
    reclaimed = store.claim_due(1, now=database_now + timedelta(seconds=61))[0]

    assert reclaimed.dispatch == original.dispatch
    assert reclaimed.token != original.token
    with pytest.raises(DispatchClaimLost):
        store.mark_enqueued(original)
    store.mark_enqueued(reclaimed)

    with migrated_engine.connect() as connection:
        dispatch = connection.execute(select(job_dispatches)).one()
    assert dispatch.status == "enqueued"


def test_duplicate_delivery_reuses_work_and_later_revision_gets_own_job(
    migrated_engine,
) -> None:
    run_id, release_id = _seed_run_and_release(migrated_engine)
    _insert_history_event(
        migrated_engine,
        run_id,
        _revision(
            run_id,
            event_time=NOW - timedelta(hours=1),
            bulletin_id="2026_0916_1100_B1",
        ),
    )
    transactions = _transactions(migrated_engine, release_id)
    first_request = _feature_request(run_id, release_id)
    first = transactions.process_event_with_features(first_request)
    replay = transactions.process_event_with_features(
        _feature_request(
            run_id,
            release_id,
            event_id=first_request.event_id,
            revision=replace(first_request.revision, event_revision_id=uuid4()),
        )
    )

    later_revision = _revision(
        run_id,
        event_time=NOW,
        bulletin_id="2026_0916_1200_B2",
        precision="minute",
        source_url="https://earthquake.phivolcs.dost.gov.ph/2026_0916_1200_B2",
    )
    later = transactions.process_event_with_features(
        _feature_request(
            run_id,
            release_id,
            event_id=first_request.event_id,
            revision=later_revision,
        )
    )

    assert replay.prediction_created is False
    assert replay.prediction_job_id == first.prediction_job_id
    assert later.revision_created is True
    assert later.prediction_created is True
    assert later.prediction_job_id != first.prediction_job_id
    assert _counts(migrated_engine) == {"events": 2, "revisions": 3, "jobs": 2, "dispatches": 2}
