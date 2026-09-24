from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import pytest
from redis import Redis
from sqlalchemy import create_engine, event, func, insert, select, text, update

from quakestrike.application.dispatch import DispatchClaim, DispatchClaimLost, PredictionDispatch
from quakestrike.application.prediction import StalePredictionAttempt
from quakestrike.domain.features import INPUT_SCHEMA_VERSION, feature_snapshot_hash
from quakestrike.domain.prediction import compose_forecast
from quakestrike.infrastructure.database.dispatch import SqlAlchemyDispatchStore
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.prediction import (
    OUTPUT_SCHEMA_VERSION,
    SqlAlchemyPredictionStore,
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
from quakestrike.infrastructure.models.deterministic_test import DeterministicTestModel
from quakestrike.infrastructure.models.release_manifest import (
    SELECTED_RELEASE_MANIFEST_URI,
    load_verified_release_manifest,
)
from quakestrike.infrastructure.models.seis import SeisModel
from quakestrike.infrastructure.queues.contracts import PredictionCommandV1
from quakestrike.infrastructure.queues.prediction_publisher import CeleryPredictionPublisher
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import ModelReleaseStartupGate
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


def seed(
    migrated_engine,
    *,
    selected_release=None,
    existing_release_id=None,
    trigger_type="manual",
    source_minute="1200",
):
    run_id, event_id, revision_id, release_id, job_id, dispatch_id, correlation_id = (
        uuid4() for _ in range(7)
    )
    if selected_release is not None:
        release_id = selected_release.release_id
    elif existing_release_id is not None:
        release_id = existing_release_id
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(ingestion_runs).values(
                run_id=run_id,
                trigger_type=trigger_type,
                status="succeeded",
                started_at=NOW,
                finished_at=NOW,
                correlation_id=correlation_id,
                bootstrap_snapshot_sha256="a" * 64 if trigger_type == "backfill" else None,
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
                source_bulletin_id=f"2026_0923_{source_minute}_B1",
                event_id=event_id,
            )
        )
        connection.execute(
            insert(earthquake_event_revisions).values(
                event_revision_id=revision_id,
                event_id=event_id,
                revision_number=1,
                ingestion_run_id=run_id,
                source_bulletin_id=f"2026_0923_{source_minute}_B1",
                source_event_group_id=f"2026_0923_{source_minute}",
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
        if existing_release_id is None:
            connection.execute(
                insert(model_releases).values(
                    model_release_id=release_id,
                    version_label="SEIS 1.0.1",
                    artifact_manifest_uri="seis-1.0.1/manifest.json",
                    artifact_manifest_hash=(
                        selected_release.manifest_hash if selected_release is not None else "a" * 64
                    ),
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


def store(migrated_engine, clock=lambda: NOW, *, configured_release_id=None):
    if configured_release_id is None:
        with migrated_engine.connect() as connection:
            configured_release_id = connection.scalar(select(model_releases.c.model_release_id))
    return SqlAlchemyPredictionStore(
        create_session_factory(migrated_engine),
        configured_release_id=configured_release_id,
        clock=clock,
    )


def test_prediction_command_completes_once_and_stops_dispatch(migrated_engine, caplog):
    command = seed(migrated_engine)

    def process():
        return handle_prediction_command(
            command.to_message(),
            store=store(migrated_engine),
            model=DeterministicTestModel(),
            logger=logging.getLogger(__name__),
        )

    with caplog.at_level(logging.INFO, logger=__name__):
        assert process() == "succeeded"
    assert process() == "unclaimed"
    claimed = next(
        record for record in caplog.records if record.event_code == "prediction_attempt_claimed"
    )
    assert claimed.context["dispatch_id"] == str(command.dispatch_id)
    assert claimed.context["job_id"] == str(command.job_id)
    assert claimed.context["correlation_id"] == str(command.correlation_id)
    assert claimed.context["attempt_id"]
    assert claimed.context["worker"]
    with migrated_engine.connect() as connection:
        job = connection.execute(
            select(prediction_jobs).where(prediction_jobs.c.job_id == command.job_id)
        ).one()
        forecast = connection.execute(select(forecasts)).one()
        attempt = connection.execute(select(prediction_attempts)).one()
        dispatch = connection.execute(
            select(job_dispatches).where(job_dispatches.c.prediction_job_id == command.job_id)
        ).one()
        alert = connection.execute(select(alert_jobs)).one()
        alert_dispatch = connection.execute(
            select(job_dispatches).where(job_dispatches.c.alert_job_id == alert.alert_job_id)
        ).one()
        assert job.status == attempt.status == "succeeded"
        assert forecast.window_start == NOW
        assert forecast.window_end == NOW + timedelta(hours=24)
        assert forecast.probability_m4_plus_24h == pytest.approx(0.24)
        assert forecast.probability_m5_plus_24h == pytest.approx(0.06)
        assert dispatch.status == "stopped"
        assert alert.forecast_id == forecast.forecast_id
        assert alert.expires_at == forecast.window_end
        assert alert.correlation_id == command.correlation_id
        assert "M4.2" in alert.message_snapshot
        assert alert.recipient_policy_snapshot["observed_anchor_magnitude"] == 4.2
        assert alert.recipient_policy_snapshot["version"] == "automatic_sms_v1"
        assert alert_dispatch.status == "pending"
        assert connection.scalar(select(func.count()).select_from(alert_jobs)) == 1
        assert connection.scalar(select(func.count()).select_from(job_dispatches)) == 2
        assert connection.scalar(select(func.count()).select_from(audit_logs)) == 1
        audit = connection.execute(select(audit_logs)).one()
        assert audit.metadata == {
            "forecast_id": str(forecast.forecast_id),
            "alert_job_id": str(alert.alert_job_id),
        }


def test_two_prediction_executions_complete_independent_jobs_concurrently(migrated_engine):
    first = seed(migrated_engine)
    with migrated_engine.connect() as connection:
        release_id = connection.scalar(select(model_releases.c.model_release_id))
    commands = [
        first,
        seed(migrated_engine, existing_release_id=release_id, source_minute="1201"),
    ]
    overlap = Barrier(2, timeout=10)

    class OverlapModel(DeterministicTestModel):
        def predict(self, features):
            overlap.wait()
            return super().predict(features)

    def process(command):
        return handle_prediction_command(
            command.to_message(),
            store=store(migrated_engine, configured_release_id=release_id),
            model=OverlapModel(),
            logger=logging.getLogger(__name__),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(process, commands))
    assert results == ["succeeded", "succeeded"]
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(prediction_attempts)) == 2
        assert connection.scalar(select(func.count()).select_from(forecasts)) == 2


def test_two_prediction_executions_racing_for_one_job_keep_one_attempt(migrated_engine):
    command = seed(migrated_engine)
    with migrated_engine.connect() as connection:
        release_id = connection.scalar(select(model_releases.c.model_release_id))
    started, finish = Event(), Event()

    class HeldModel(DeterministicTestModel):
        def predict(self, features):
            started.set()
            assert finish.wait(10)
            return super().predict(features)

    def process(model):
        return handle_prediction_command(
            command.to_message(),
            store=store(migrated_engine, configured_release_id=release_id),
            model=model,
            logger=logging.getLogger(__name__),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(process, HeldModel())
        try:
            assert started.wait(10)
            assert pool.submit(process, DeterministicTestModel()).result(timeout=10) == "unclaimed"
        finally:
            finish.set()
        assert first.result(timeout=10) == "succeeded"
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(prediction_attempts)) == 1
        assert connection.scalar(select(func.count()).select_from(forecasts)) == 1


@pytest.mark.parametrize("trigger_type,expired", [("backfill", False), ("manual", True)])
def test_backfill_and_expired_forecasts_create_no_alert(migrated_engine, trigger_type, expired):
    command = seed(migrated_engine, trigger_type=trigger_type)
    clock = NOW + timedelta(hours=24) if expired else NOW
    assert (
        handle_prediction_command(
            command.to_message(),
            store=store(migrated_engine, clock=lambda: clock),
            model=DeterministicTestModel(),
            logger=logging.getLogger(__name__),
        )
        == "succeeded"
    )
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(forecasts)) == 1
        assert connection.scalar(select(func.count()).select_from(alert_jobs)) == 0
        assert connection.scalar(select(func.count()).select_from(job_dispatches)) == 1


def test_forecast_from_another_model_release_creates_no_alert(migrated_engine):
    command = seed(migrated_engine)
    assert (
        handle_prediction_command(
            command.to_message(),
            store=store(migrated_engine, configured_release_id=uuid4()),
            model=DeterministicTestModel(),
            logger=logging.getLogger(__name__),
        )
        == "succeeded"
    )
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(forecasts)) == 1
        assert connection.scalar(select(func.count()).select_from(alert_jobs)) == 0


def test_historical_revision_creates_no_alert(migrated_engine):
    command = seed(migrated_engine)
    with migrated_engine.begin() as connection:
        previous = connection.execute(select(earthquake_event_revisions)).one()
        connection.execute(
            insert(earthquake_bulletin_event_identities).values(
                source_bulletin_id="2026_0923_1201_B1", event_id=previous.event_id
            )
        )
        connection.execute(
            insert(earthquake_event_revisions).values(
                **(
                    dict(previous._mapping)
                    | {
                        "event_revision_id": uuid4(),
                        "revision_number": 2,
                        "source_bulletin_id": "2026_0923_1201_B1",
                        "source_event_group_id": "2026_0923_1201",
                    }
                )
            )
        )
    assert (
        handle_prediction_command(
            command.to_message(),
            store=store(migrated_engine),
            model=DeterministicTestModel(),
            logger=logging.getLogger(__name__),
        )
        == "succeeded"
    )
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(forecasts)) == 1
        assert connection.scalar(select(func.count()).select_from(alert_jobs)) == 0


def test_alert_dispatch_failure_rolls_back_forecast_completion(migrated_engine):
    command = seed(migrated_engine)
    repository = store(migrated_engine)
    claim = repository.claim(command.dispatch_id, command.job_id, command.correlation_id)
    assert claim is not None

    def reject_alert_dispatch(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO job_dispatches"):
            raise RuntimeError("alert dispatch insert failed")

    event.listen(migrated_engine, "before_cursor_execute", reject_alert_dispatch)
    try:
        with pytest.raises(RuntimeError, match="alert dispatch insert failed"):
            repository.complete(
                claim, compose_forecast(DeterministicTestModel().predict(claim.features), NOW)
            )
    finally:
        event.remove(migrated_engine, "before_cursor_execute", reject_alert_dispatch)
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(forecasts)) == 0
        assert connection.scalar(select(func.count()).select_from(alert_jobs)) == 0
        assert connection.scalar(select(func.count()).select_from(audit_logs)) == 0
        assert connection.scalar(select(prediction_jobs.c.status)) == "running"
        assert connection.scalar(select(prediction_attempts.c.status)) == "running"
        assert connection.scalar(select(job_dispatches.c.status)) == "enqueued"


def test_real_seis_bundle_persists_known_forecast(migrated_engine):
    artifact_directory = Path(os.environ.get("MODEL_ARTIFACT_DIRECTORY", "model-artifacts"))
    if not (artifact_directory / SELECTED_RELEASE_MANIFEST_URI).is_file():
        pytest.skip("The ignored SEIS 1.0.1 bundle is unavailable.")
    if any(importlib.util.find_spec(name) is None for name in ("catboost", "lightgbm")):
        pytest.skip("The optional SEIS native dependencies are unavailable.")
    release = load_verified_release_manifest(
        artifact_directory, SELECTED_RELEASE_MANIFEST_URI, require_selected_policy=True
    )
    command = seed(migrated_engine, selected_release=release)
    settings = Settings(
        _env_file=None,
        database_url=os.environ["TEST_DATABASE_URL"],
        redis_url=os.environ["TEST_REDIS_URL"],
        phivolcs_catalog_url="https://example.invalid/catalog",
        model_release_id=release.release_id,
        model_artifact_directory=artifact_directory,
    )
    assert ModelReleaseStartupGate(settings).check().ready
    model = SeisModel(artifact_directory, release.release_id)
    assert (
        handle_prediction_command(
            command.to_message(),
            store=store(migrated_engine),
            model=model,
            logger=logging.getLogger(__name__),
        )
        == "succeeded"
    )
    with migrated_engine.connect() as connection:
        forecast = connection.execute(select(forecasts)).one()
        assert forecast.probability_m1_plus_24h == pytest.approx(0.39094539947013085)
        assert forecast.expected_m1_plus_count_24h == pytest.approx(0.7486037220152986)
        assert forecast.maximum_magnitude_q05_24h == pytest.approx(1.8372190888812674)
        assert forecast.maximum_magnitude_q50_24h == pytest.approx(2.815279071307258)
        assert forecast.maximum_magnitude_q95_24h == pytest.approx(4.97934202670072)
        assert forecast.activity_radius_median_km_24h == pytest.approx(11.585661189276763)
        assert connection.scalar(select(prediction_jobs.c.status)) == "succeeded"


def test_published_v1_command_is_consumed_by_a_running_worker(migrated_engine):
    command = seed(migrated_engine)
    with migrated_engine.connect() as connection:
        release_id = connection.scalar(select(model_releases.c.model_release_id))
    settings = Settings(
        _env_file=None,
        database_url=os.environ["TEST_DATABASE_URL"],
        redis_url=os.environ["TEST_REDIS_URL"],
        phivolcs_catalog_url="https://example.invalid/catalog",
        model_release_id=release_id,
    )
    app = create_prediction_app(settings, command_handler=lambda _: "unused")
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
            "from quakestrike.infrastructure.models.deterministic_test "
            "import DeterministicTestModel; "
            "run_prediction(Settings(_env_file=None), model=DeterministicTestModel())",
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


def test_two_queued_prediction_replicas_execute_independent_jobs_together(
    migrated_engine, tmp_path
):
    first = seed(migrated_engine)
    with migrated_engine.connect() as connection:
        release_id = connection.scalar(select(model_releases.c.model_release_id))
    second = seed(migrated_engine, existing_release_id=release_id, source_minute="1201")
    settings = Settings(
        _env_file=None,
        database_url=os.environ["TEST_DATABASE_URL"],
        redis_url=os.environ["TEST_REDIS_URL"],
        phivolcs_catalog_url="https://example.invalid/catalog",
        model_release_id=release_id,
    )
    app = create_prediction_app(settings, command_handler=lambda _: "unused")
    redis_client = Redis.from_url(settings.redis_url)
    redis_client.delete("prediction")
    names = ("prediction-worker@replica-one", "prediction-worker@replica-two")
    script = """
import os
import time
from pathlib import Path
from quakestrike.infrastructure.models.deterministic_test import DeterministicTestModel
from quakestrike.infrastructure.settings import Settings
from quakestrike.prediction_worker.worker import run_prediction

class RendezvousModel(DeterministicTestModel):
    def predict(self, features):
        marker_directory = Path(os.environ["PREDICTION_TEST_MARKER_DIR"])
        (marker_directory / str(os.getpid())).touch()
        deadline = time.monotonic() + 10
        while len(list(marker_directory.iterdir())) < 2:
            if time.monotonic() >= deadline:
                raise RuntimeError("A second replica did not start inference")
            time.sleep(0.05)
        return super().predict(features)

run_prediction(
    Settings(_env_file=None), model=RendezvousModel(),
    hostname=os.environ["PREDICTION_TEST_HOSTNAME"],
)
"""
    environment = os.environ | {
        "DATABASE_URL": settings.database_url,
        "REDIS_URL": settings.redis_url,
        "PHIVOLCS_CATALOG_URL": settings.phivolcs_catalog_url,
        "MODEL_RELEASE_ID": str(release_id),
        "PREDICTION_TEST_MARKER_DIR": str(tmp_path),
    }
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", script],
            env=environment | {"PREDICTION_TEST_HOSTNAME": name},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        for name in names
    ]
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            queues = app.control.inspect(destination=list(names), timeout=1).active_queues() or {}
            if all(name in queues for name in names):
                break
            assert all(worker.poll() is None for worker in workers)
            time.sleep(0.2)
        else:
            pytest.fail("Both Prediction Worker replicas did not become ready.")
        publisher = CeleryPredictionPublisher(app)
        for command in (first, second):
            publisher.publish(
                PredictionDispatch(command.dispatch_id, command.job_id, command.correlation_id)
            )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with migrated_engine.connect() as connection:
                if connection.scalar(select(func.count()).select_from(forecasts)) == 2:
                    break
            assert all(worker.poll() is None for worker in workers)
            time.sleep(0.2)
        else:
            pytest.fail("Two replicas did not complete independent queued predictions.")
    finally:
        for worker in workers:
            worker.terminate()
        for worker in workers:
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
        redis_client.delete("prediction")
        redis_client.close()
    assert len(list(tmp_path.iterdir())) == 2
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(prediction_attempts)) == 2
        assert connection.scalar(select(func.count()).select_from(forecasts)) == 2


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
    assert repository.claim(command.dispatch_id, command.job_id, command.correlation_id) is None
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


def test_runtime_failures_retry_on_schedule_then_stop_with_stable_ids(migrated_engine):
    command = seed(migrated_engine)
    current = [NOW]
    prediction_store = store(migrated_engine, clock=lambda: current[0])
    dispatch_store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))

    class FailingModel:
        def predict(self, features):
            raise RuntimeError("model unavailable")

    for attempt_number, delay in enumerate((30, 120, 600), start=1):
        assert (
            handle_prediction_command(
                command.to_message(),
                store=prediction_store,
                model=FailingModel(),
                logger=logging.getLogger(__name__),
            )
            == "retry_wait"
        )
        with migrated_engine.connect() as connection:
            job = connection.execute(select(prediction_jobs)).one()
            dispatch = connection.execute(select(job_dispatches)).one()
            assert job.status == "retry_wait"
            assert job.next_attempt_at == current[0] + timedelta(seconds=delay)
            assert dispatch.dispatch_id == command.dispatch_id
            assert dispatch.status == "enqueued"
            assert (
                connection.scalar(select(func.count()).select_from(prediction_attempts))
                == attempt_number
            )
        assert dispatch_store.claim_due(1, now=current[0]) == ()
        current[0] += timedelta(seconds=delay)
        claim = dispatch_store.claim_due(1, now=current[0])[0]
        assert claim.dispatch == PredictionDispatch(
            command.dispatch_id, command.job_id, command.correlation_id
        )
        dispatch_store.mark_enqueued(claim)

    assert (
        handle_prediction_command(
            command.to_message(),
            store=prediction_store,
            model=FailingModel(),
            logger=logging.getLogger(__name__),
        )
        == "failed"
    )
    with migrated_engine.connect() as connection:
        job = connection.execute(select(prediction_jobs)).one()
        dispatch = connection.execute(select(job_dispatches)).one()
        attempts = connection.execute(
            select(prediction_attempts).order_by(prediction_attempts.c.attempt_number)
        ).all()
        assert job.job_id == command.job_id
        assert job.status == "failed"
        assert job.next_attempt_at is None
        assert job.last_error_code == "model_runtime_error"
        assert dispatch.dispatch_id == command.dispatch_id
        assert dispatch.status == "stopped"
        assert [attempt.attempt_number for attempt in attempts] == [1, 2, 3, 4]
        assert [attempt.status for attempt in attempts] == ["failed"] * 4
        assert connection.scalar(select(func.count()).select_from(forecasts)) == 0


def test_transient_forecast_write_failure_retries_without_partial_result(migrated_engine):
    command = seed(migrated_engine)
    current = [NOW]
    prediction_store = store(migrated_engine, clock=lambda: current[0])

    def reject_forecast_once(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO forecasts"):
            raise RuntimeError("database write interrupted")

    event.listen(migrated_engine, "before_cursor_execute", reject_forecast_once)
    try:
        assert (
            handle_prediction_command(
                command.to_message(),
                store=prediction_store,
                model=DeterministicTestModel(),
                logger=logging.getLogger(__name__),
            )
            == "retry_wait"
        )
    finally:
        event.remove(migrated_engine, "before_cursor_execute", reject_forecast_once)
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(forecasts)) == 0
        assert connection.scalar(select(func.count()).select_from(alert_jobs)) == 0
        assert connection.scalar(select(prediction_jobs.c.status)) == "retry_wait"
        assert connection.scalar(select(prediction_jobs.c.last_error_code)) == "persistence_error"

    current[0] += timedelta(seconds=30)
    dispatch_store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))
    claim = dispatch_store.claim_due(1, now=current[0])[0]
    dispatch_store.mark_enqueued(claim)
    assert (
        handle_prediction_command(
            command.to_message(),
            store=prediction_store,
            model=DeterministicTestModel(),
            logger=logging.getLogger(__name__),
        )
        == "succeeded"
    )
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(forecasts)) == 1
        assert connection.scalar(select(func.count()).select_from(prediction_attempts)) == 2


def test_prediction_dispatch_recovery_fences_live_lease_and_old_submission_token(migrated_engine):
    command = seed(migrated_engine)
    current = [NOW]
    prediction_store = store(migrated_engine, clock=lambda: current[0])
    dispatch_store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))
    first = prediction_store.claim(command.dispatch_id, command.job_id, command.correlation_id)
    assert first is not None
    assert dispatch_store.claim_due(1, now=NOW + timedelta(minutes=14)) == ()

    current[0] += timedelta(minutes=15)
    assert dispatch_store.claim_due(1, now=current[0]) == ()
    with migrated_engine.connect() as connection:
        job = connection.execute(select(prediction_jobs)).one()
        assert job.status == "retry_wait"
        assert job.next_attempt_at == current[0] + timedelta(seconds=30)
        assert connection.scalar(select(prediction_attempts.c.status)) == "abandoned"
    assert dispatch_store.claim_due(1, now=current[0] + timedelta(seconds=29)) == ()
    current[0] += timedelta(seconds=30)
    recovered = dispatch_store.claim_due(1, now=current[0])[0]
    old_token = uuid4()
    with pytest.raises(DispatchClaimLost):
        dispatch_store.mark_enqueued(DispatchClaim(recovered.dispatch, old_token))
    dispatch_store.mark_enqueued(recovered)
    second = prediction_store.claim(command.dispatch_id, command.job_id, command.correlation_id)
    assert second is not None and second.attempt_id != first.attempt_id
    with pytest.raises(StalePredictionAttempt):
        prediction_store.fail(
            first, "model_runtime_error", "The prediction model could not finish."
        )
    with migrated_engine.connect() as connection:
        attempts = connection.execute(
            select(prediction_attempts).order_by(prediction_attempts.c.attempt_number)
        ).all()
        assert [attempt.status for attempt in attempts] == ["abandoned", "running"]
        assert connection.scalar(select(func.count()).select_from(job_dispatches)) == 1


def test_broker_loss_republishes_pending_prediction_without_replacing_dispatch(migrated_engine):
    command = seed(migrated_engine)
    with migrated_engine.begin() as connection:
        connection.execute(
            update(job_dispatches)
            .where(job_dispatches.c.dispatch_id == command.dispatch_id)
            .values(last_dispatched_at=NOW, attempt_count=0)
        )
    dispatch_store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))
    assert dispatch_store.claim_due(1, now=NOW + timedelta(minutes=14)) == ()
    claim = dispatch_store.claim_due(1, now=NOW + timedelta(minutes=15))[0]
    assert claim.dispatch.dispatch_id == command.dispatch_id
    assert (
        dispatch_store.mark_retry(
            claim, RuntimeError("broker unavailable"), now=NOW + timedelta(minutes=15)
        )
        == "retry_wait"
    )
    assert dispatch_store.claim_due(1, now=NOW + timedelta(minutes=15, seconds=29)) == ()
    retry = dispatch_store.claim_due(1, now=NOW + timedelta(minutes=15, seconds=30))[0]
    dispatch_store.mark_enqueued(retry)
    with migrated_engine.connect() as connection:
        dispatch = connection.execute(select(job_dispatches)).one()
        assert dispatch.dispatch_id == command.dispatch_id
        assert dispatch.status == "enqueued"
        assert dispatch.attempt_count == 0
        assert connection.scalar(select(prediction_jobs.c.status)) == "pending"


def test_prediction_submission_exhaustion_fails_unclaimed_job(migrated_engine):
    command = seed(migrated_engine)
    with migrated_engine.begin() as connection:
        connection.execute(
            update(job_dispatches)
            .where(job_dispatches.c.dispatch_id == command.dispatch_id)
            .values(status="pending", next_dispatch_at=NOW, last_dispatched_at=None)
        )
    dispatch_store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))
    now = NOW
    for delay in (30, 120, 600):
        claim = dispatch_store.claim_due(1, now=now)[0]
        assert (
            dispatch_store.mark_retry(claim, RuntimeError("broker unavailable"), now=now)
            == "retry_wait"
        )
        now += timedelta(seconds=delay)
    claim = dispatch_store.claim_due(1, now=now)[0]
    assert (
        dispatch_store.mark_retry(claim, RuntimeError("broker unavailable"), now=now) == "stopped"
    )
    with migrated_engine.connect() as connection:
        job = connection.execute(select(prediction_jobs)).one()
        dispatch = connection.execute(select(job_dispatches)).one()
        assert job.job_id == command.job_id
        assert job.status == "failed"
        assert job.last_error_code == "dispatch_exhausted"
        assert dispatch.dispatch_id == command.dispatch_id
        assert dispatch.status == "stopped"
        assert connection.scalar(select(func.count()).select_from(prediction_attempts)) == 0


def test_uncertain_submission_does_not_strand_a_live_prediction_attempt(migrated_engine):
    command = seed(migrated_engine)
    with migrated_engine.begin() as connection:
        connection.execute(
            update(job_dispatches)
            .where(job_dispatches.c.dispatch_id == command.dispatch_id)
            .values(status="pending", next_dispatch_at=NOW, last_dispatched_at=None)
        )
    dispatch_store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))
    submission = dispatch_store.claim_due(1, now=NOW)[0]
    current = [NOW]
    prediction_store = store(migrated_engine, clock=lambda: current[0])
    first = prediction_store.claim(command.dispatch_id, command.job_id, command.correlation_id)
    assert first is not None
    with migrated_engine.begin() as connection:
        connection.execute(
            update(job_dispatches)
            .where(job_dispatches.c.dispatch_id == command.dispatch_id)
            .values(attempt_count=4)
        )
    assert (
        dispatch_store.mark_retry(submission, RuntimeError("broker outcome unknown"), now=NOW)
        == "retry_wait"
    )
    assert dispatch_store.claim_due(1, now=NOW + timedelta(minutes=14)) == ()
    current[0] += timedelta(minutes=16)
    assert dispatch_store.claim_due(1, now=current[0]) == ()
    recovery = dispatch_store.claim_due(1, now=current[0])[0]
    dispatch_store.mark_enqueued(recovery)
    second = prediction_store.claim(command.dispatch_id, command.job_id, command.correlation_id)
    assert second is not None and second.attempt_id != first.attempt_id
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(prediction_jobs.c.status)) == "running"
        assert connection.scalar(select(job_dispatches.c.dispatch_id)) == command.dispatch_id
        assert connection.execute(
            select(prediction_attempts.c.status).order_by(prediction_attempts.c.attempt_number)
        ).scalars().all() == ["abandoned", "running"]


def test_fourth_expired_attempt_is_abandoned_and_job_stops(migrated_engine):
    command = seed(migrated_engine)
    current = [NOW]
    repository = store(migrated_engine, clock=lambda: current[0])
    for delay in (30, 120, 600):
        claim = repository.claim(command.dispatch_id, command.job_id, command.correlation_id)
        assert claim is not None
        current[0] += timedelta(minutes=15, seconds=delay)
        assert repository.claim(command.dispatch_id, command.job_id, command.correlation_id) is None
    fourth = repository.claim(command.dispatch_id, command.job_id, command.correlation_id)
    assert fourth is not None
    current[0] += timedelta(minutes=16)
    dispatch_store = SqlAlchemyDispatchStore(create_session_factory(migrated_engine))
    assert dispatch_store.claim_due(1, now=current[0]) == ()
    with migrated_engine.connect() as connection:
        job = connection.execute(select(prediction_jobs)).one()
        dispatch = connection.execute(select(job_dispatches)).one()
        attempts = connection.execute(
            select(prediction_attempts).order_by(prediction_attempts.c.attempt_number)
        ).all()
        assert job.status == "failed"
        assert job.last_error_code == "lease_expired"
        assert dispatch.status == "stopped"
        assert [attempt.attempt_number for attempt in attempts] == [1, 2, 3, 4]
        assert [attempt.status for attempt in attempts] == ["abandoned"] * 4


def test_prediction_runs_with_the_provisioned_worker_role(migrated_engine):
    command = seed(migrated_engine)
    with migrated_engine.connect() as connection:
        release_id = connection.scalar(select(model_releases.c.model_release_id))
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
        repository = store(worker_engine, configured_release_id=release_id)
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
            assert connection.scalar(text("SELECT count(*) FROM alert_jobs")) == 1
            assert (
                connection.scalar(
                    text("SELECT has_table_privilege(current_user, 'forecasts', 'UPDATE')")
                )
                is False
            )
    finally:
        worker_engine.dispose()
