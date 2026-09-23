from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from redis import Redis
from sqlalchemy import create_engine, event, func, insert, select, text

from quakestrike.application.dispatch import PredictionDispatch
from quakestrike.domain.features import INPUT_SCHEMA_VERSION, feature_snapshot_hash
from quakestrike.domain.prediction import compose_forecast
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.prediction import (
    OUTPUT_SCHEMA_VERSION,
    SqlAlchemyPredictionStore,
    StalePredictionAttempt,
)
from quakestrike.infrastructure.database.tables import (
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
from quakestrike.infrastructure.models.deterministic_test import DeterministicTestModel
from quakestrike.infrastructure.queues.contracts import PredictionCommandV1
from quakestrike.infrastructure.queues.prediction_publisher import CeleryPredictionPublisher
from quakestrike.infrastructure.settings import Settings
from quakestrike.prediction_worker.worker import create_prediction_app, handle_prediction_command

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 23, 12, tzinfo=UTC)
SNAPSHOT = {
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


def seed(migrated_engine):
    run_id, event_id, revision_id, release_id, job_id, dispatch_id, correlation_id = (
        uuid4() for _ in range(7)
    )
    with migrated_engine.begin() as connection:
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
                source_bulletin_id="2026_0923_1200_B1",
                event_id=event_id,
            )
        )
        connection.execute(
            insert(earthquake_event_revisions).values(
                event_revision_id=revision_id,
                event_id=event_id,
                revision_number=1,
                ingestion_run_id=run_id,
                source_bulletin_id="2026_0923_1200_B1",
                source_event_group_id="2026_0923_1200",
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
            insert(model_releases).values(
                model_release_id=release_id,
                version_label="SEIS 1.0.1",
                artifact_manifest_uri="model-artifacts/seis-1.0.1/manifest.json",
                artifact_manifest_hash="a" * 64,
                input_schema_version=INPUT_SCHEMA_VERSION,
                output_schema_version=OUTPUT_SCHEMA_VERSION,
            )
        )
        connection.execute(
            insert(prediction_jobs).values(
                job_id=job_id,
                event_revision_id=revision_id,
                model_release_id=release_id,
                input_snapshot_hash=feature_snapshot_hash(SNAPSHOT),
                input_snapshot_json=SNAPSHOT,
                idempotency_key=str(job_id),
                correlation_id=correlation_id,
            )
        )
        connection.execute(
            insert(job_dispatches).values(
                dispatch_id=dispatch_id,
                prediction_job_id=job_id,
                status="enqueued",
                next_dispatch_at=None,
                last_dispatched_at=NOW,
            )
        )
    return PredictionCommandV1(
        dispatch_id=dispatch_id, job_id=job_id, correlation_id=correlation_id
    )


def store(migrated_engine, clock=lambda: NOW):
    return SqlAlchemyPredictionStore(create_session_factory(migrated_engine), clock=clock)


def test_prediction_command_completes_once_and_stops_dispatch(migrated_engine):
    command = seed(migrated_engine)

    def process():
        return handle_prediction_command(
            command.to_message(),
            store=store(migrated_engine),
            model=DeterministicTestModel(),
            logger=logging.getLogger(__name__),
        )

    assert process() == "succeeded"
    assert process() == "unclaimed"
    with migrated_engine.connect() as connection:
        job = connection.execute(
            select(prediction_jobs).where(prediction_jobs.c.job_id == command.job_id)
        ).one()
        forecast = connection.execute(select(forecasts)).one()
        attempt = connection.execute(select(prediction_attempts)).one()
        dispatch = connection.execute(select(job_dispatches)).one()
        assert job.status == attempt.status == "succeeded"
        assert forecast.window_start == NOW
        assert forecast.window_end == NOW + timedelta(hours=24)
        assert forecast.probability_m4_plus_24h == pytest.approx(0.24)
        assert forecast.probability_m5_plus_24h == pytest.approx(0.06)
        assert dispatch.status == "stopped"
        assert connection.scalar(select(func.count()).select_from(audit_logs)) == 1


def test_published_v1_command_is_consumed_by_a_running_worker(migrated_engine):
    command = seed(migrated_engine)
    settings = Settings(
        _env_file=None,
        database_url=os.environ["TEST_DATABASE_URL"],
        redis_url=os.environ["TEST_REDIS_URL"],
        phivolcs_catalog_url="https://example.invalid/catalog",
        model_release_id=uuid4(),
    )
    app = create_prediction_app(settings)
    redis_client = Redis.from_url(settings.redis_url)
    redis_client.delete("prediction")
    environment = os.environ | {
        "DATABASE_URL": settings.database_url,
        "REDIS_URL": settings.redis_url,
        "PHIVOLCS_CATALOG_URL": settings.phivolcs_catalog_url,
        "MODEL_RELEASE_ID": str(settings.model_release_id),
    }
    worker = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from quakestrike.infrastructure.settings import Settings; "
            "from quakestrike.prediction_worker.worker import run_prediction; "
            "run_prediction(Settings(_env_file=None))",
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        CeleryPredictionPublisher(app).publish(
            PredictionDispatch(command.dispatch_id, command.job_id, command.correlation_id)
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with migrated_engine.connect() as connection:
                if connection.scalar(select(func.count()).select_from(forecasts)) == 1:
                    break
            if worker.poll() is not None:
                pytest.fail(f"Prediction worker exited: {worker.stdout.read()[-2000:]}")
            time.sleep(0.2)
        else:
            pytest.fail("Prediction worker did not consume the queued command.")
    finally:
        worker.terminate()
        try:
            worker.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.communicate(timeout=5)
        redis_client.delete("prediction")
        redis_client.close()
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(forecasts)) == 1


def test_invalid_output_is_durable_and_creates_no_forecast(migrated_engine):
    command = seed(migrated_engine)

    class InvalidModel:
        def predict(self, features):
            return DeterministicTestModel().predict(features) | {"m4_given_m1": float("nan")}

    assert (
        handle_prediction_command(
            command.to_message(),
            store=store(migrated_engine),
            model=InvalidModel(),
            logger=logging.getLogger(__name__),
        )
        == "failed"
    )
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(forecasts)) == 0
        assert connection.scalar(select(prediction_jobs.c.last_error_code)) == "invalid_output"
        assert connection.scalar(select(prediction_attempts.c.error_code)) == "invalid_output"
        assert connection.scalar(select(audit_logs.c.reason_code)) == "invalid_output"


def test_expired_attempt_is_abandoned_and_stale_completion_is_audited(migrated_engine):
    command = seed(migrated_engine)
    current = [NOW]
    repository = store(migrated_engine, clock=lambda: current[0])
    first = repository.claim(command.dispatch_id, command.job_id, command.correlation_id)
    assert first is not None
    assert repository.claim(command.dispatch_id, command.job_id, command.correlation_id) is None
    current[0] += timedelta(minutes=16)
    second = repository.claim(command.dispatch_id, command.job_id, command.correlation_id)
    assert second is not None and second.execution_id != first.execution_id
    with pytest.raises(StalePredictionAttempt):
        repository.complete(
            first, compose_forecast(DeterministicTestModel().predict(first.features), NOW)
        )
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(forecasts)) == 0
        assert connection.scalar(select(func.count()).select_from(prediction_attempts)) == 2
        assert connection.scalar(select(audit_logs.c.reason_code)) == "stale_execution_token"
    assert (
        repository.complete(
            second, compose_forecast(DeterministicTestModel().predict(second.features), NOW)
        )
        is not None
    )


def test_prediction_runs_with_the_provisioned_worker_role(migrated_engine):
    command = seed(migrated_engine)
    script = (
        Path(__file__).resolve().parents[3] / "infrastructure/postgres/provision-roles.sh"
    ).read_text(encoding="utf-8")
    grants = script.split("  grant-worker)", 1)[1].split("<<'SQL'\n", 1)[1].split("\nSQL", 1)[0]
    with migrated_engine.begin() as connection:
        connection.exec_driver_sql(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
            "'quakestrike_worker') THEN CREATE ROLE quakestrike_worker; END IF; END $$"
        )
        connection.exec_driver_sql("GRANT USAGE ON SCHEMA public TO quakestrike_worker")
        for statement in grants.split(";"):
            if statement.strip():
                connection.exec_driver_sql(statement)

    worker_engine = create_engine(os.environ["TEST_DATABASE_URL"])

    @event.listens_for(worker_engine, "connect")
    def use_worker_role(dbapi_connection, connection_record):
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET ROLE quakestrike_worker")

    try:
        repository = store(worker_engine)
        assert (
            handle_prediction_command(
                command.to_message(),
                store=repository,
                model=DeterministicTestModel(),
                logger=logging.getLogger(__name__),
            )
            == "succeeded"
        )
        with worker_engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM forecasts")) == 1
            assert (
                connection.scalar(
                    text("SELECT has_table_privilege(current_user, 'forecasts', 'UPDATE')")
                )
                is False
            )
    finally:
        worker_engine.dispose()
