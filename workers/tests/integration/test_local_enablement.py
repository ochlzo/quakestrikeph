"""One isolated proof from preserved history through a scheduled prediction command."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from kombu import Connection
from redis import Redis
from sqlalchemy import func, insert, select

from quakestrike.application.bootstrap import HistoricalBootstrapOperation
from quakestrike.application.dispatch import DurableDispatcher
from quakestrike.application.reconciliation import ReconcileCurrentCatalog
from quakestrike.application.startup import evaluate_startup_gates
from quakestrike.data_ingestor.worker import handle_ingestion_command
from quakestrike.domain.features import INPUT_SCHEMA_VERSION, feature_snapshot_hash
from quakestrike.infrastructure import startup
from quakestrike.infrastructure.bootstrap import FileBootstrapEvidenceStore, load_bootstrap_snapshot
from quakestrike.infrastructure.database.dispatch import SqlAlchemyDispatchStore
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.database.tables import (
    earthquake_event_revisions,
    earthquake_events,
    ingestion_run_inputs,
    ingestion_runs,
    job_dispatches,
    model_releases,
    prediction_jobs,
)
from quakestrike.infrastructure.logging.reconciliation import (
    StructuredReconciliationDiagnosticReporter,
)
from quakestrike.infrastructure.models.release_manifest import VerifiedReleaseManifest
from quakestrike.infrastructure.phivolcs.client import PhivolcsCatalogClient
from quakestrike.infrastructure.queues.celery_app import (
    INGESTION_QUEUE,
    INGESTION_TASK_NAME,
    PREDICTION_QUEUE,
    create_celery_app,
)
from quakestrike.infrastructure.queues.contracts import (
    IngestionCommandV1,
    PredictionCommandV1,
)
from quakestrike.infrastructure.queues.ingestion_publisher import CeleryIngestionPublisher
from quakestrike.infrastructure.queues.prediction_publisher import (
    PREDICTION_TASK_NAME,
    CeleryPredictionPublisher,
)
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import phase_one_startup_gates
from quakestrike.scheduler.beat import DurableBeatScheduler, run_scheduled_ingestion_tick

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures"
CATALOG_URL = "https://earthquake.phivolcs.dost.gov.ph/"
NOW = datetime(2099, 9, 19, 0, 0, tzinfo=UTC)


class _VerifiedRelease:
    def __init__(self, release_id):
        self.release_id = release_id

    def is_verified(self, release_id) -> bool:
        return release_id == self.release_id


class _Response:
    status_code = 200

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.headers = {"Content-Type": "text/html", "Content-Length": str(len(body))}

    def iter_content(self, chunk_size: int):
        yield from (
            self.body[index : index + chunk_size] for index in range(0, len(self.body), chunk_size)
        )

    def close(self) -> None:
        pass


class _FixtureSession:
    def __init__(self) -> None:
        directory = FIXTURES / "phivolcs"
        self.bodies = {
            CATALOG_URL: (directory / "local_proof_catalog.html").read_bytes(),
            CATALOG_URL + "2026_Earthquake_Information/August/2026_0827_1200_B1.html": (
                directory / "local_proof_corrected_detail.html"
            ).read_bytes(),
            CATALOG_URL + "2026_Earthquake_Information/September/2026_0901_1300_B1.html": (
                directory / "local_proof_new_detail.html"
            ).read_bytes(),
        }
        self.calls: list[str] = []

    def get(self, url: str, **_kwargs: object) -> _Response:
        self.calls.append(url)
        return _Response(self.bodies[url])


def _counts(connection) -> tuple[int, int, int, int, int]:
    return tuple(
        connection.scalar(select(func.count()).select_from(table))
        for table in (
            ingestion_runs,
            earthquake_events,
            earthquake_event_revisions,
            prediction_jobs,
            job_dispatches,
        )
    )


def test_ready_history_beat_ingestion_and_prediction_queue_are_replay_safe(
    migrated_engine, tmp_path: Path, monkeypatch
) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    redis_url = os.environ.get("TEST_REDIS_URL")
    if database_url is None or redis_url is None:
        pytest.skip("TEST_DATABASE_URL and TEST_REDIS_URL are required.")

    redis_client = Redis.from_url(redis_url)
    redis_client.delete(INGESTION_QUEUE, PREDICTION_QUEUE)
    try:
        release_id = uuid4()
        with migrated_engine.begin() as connection:
            connection.execute(
                insert(model_releases).values(
                    model_release_id=release_id,
                    version_label="SEIS 1.0",
                    artifact_manifest_uri="seis-1.0/manifest.json",
                    artifact_manifest_hash="a" * 64,
                    input_schema_version=INPUT_SCHEMA_VERSION,
                    output_schema_version="quakestrike.prediction-output.v1",
                )
            )
        session_factory = create_session_factory(migrated_engine)
        store = SqlAlchemyIngestionTransactions(
            session_factory, model_release_verifier=_VerifiedRelease(release_id)
        )
        reporter = StructuredReconciliationDiagnosticReporter(logging.getLogger(__name__))
        manifest_path = tmp_path / "bootstrap-readiness.json"
        snapshot_path = FIXTURES / "bootstrap" / "historical_snapshot.json"
        history_coverage = load_bootstrap_snapshot(snapshot_path).coverage.history_coverage()
        bootstrap = HistoricalBootstrapOperation(
            evidence=FileBootstrapEvidenceStore(
                manifest_path, evidence_directory=tmp_path / "preserved"
            ),
            store=store,
            diagnostic_reporter=reporter,
            model_release_id=release_id,
        ).execute(snapshot_path, manifest_path)
        assert bootstrap.exit_code == 0

        settings = Settings(
            _env_file=None,
            database_url=database_url,
            redis_url=redis_url,
            phivolcs_catalog_url=CATALOG_URL,
            model_release_id=release_id,
            bootstrap_run_manifest=manifest_path,
        )
        manifest = VerifiedReleaseManifest(
            release_id=release_id,
            version_label="SEIS 1.0",
            input_schema_version=INPUT_SCHEMA_VERSION,
            output_schema_version="quakestrike.prediction-output.v1",
            manifest_uri="seis-1.0/manifest.json",
            manifest_hash="a" * 64,
            artifact_paths=(),
        )
        monkeypatch.setattr(startup, "load_verified_release_manifest", lambda *_, **__: manifest)
        readiness = evaluate_startup_gates(phase_one_startup_gates(settings))
        assert readiness.ready is True
        assert {gate.name for gate in readiness.results} == {
            "migration-state",
            "model-release",
            "bootstrap-readiness",
            "postgres-connectivity",
            "redis-connectivity",
        }
        bootstrap_gate = next(
            gate for gate in readiness.results if gate.name == "bootstrap-readiness"
        )
        assert int(bootstrap_gate.details["usable_history_count"]) > 0

        with migrated_engine.connect() as connection:
            before = _counts(connection)
            original = connection.execute(
                select(earthquake_event_revisions).where(
                    earthquake_event_revisions.c.source_bulletin_id == "2026_0827_1200_B1"
                )
            ).one()

        app = create_celery_app(
            settings, ingestion_tick=lambda: run_scheduled_ingestion_tick(store, clock=lambda: NOW)
        )
        scheduler = DurableBeatScheduler(app)
        scheduler.apply_entry(scheduler.schedule["durable-ingestion-tick"])
        with migrated_engine.connect() as connection:
            scheduled = connection.execute(
                select(ingestion_runs, job_dispatches)
                .join(job_dispatches, job_dispatches.c.ingestion_run_id == ingestion_runs.c.run_id)
                .where(ingestion_runs.c.trigger_type == "scheduled")
            ).one()
        run_id = scheduled.run_id
        dispatch_id = scheduled.dispatch_id
        assert scheduled.status == "pending"
        assert scheduled.correlation_id is not None
        with migrated_engine.connect() as connection:
            assert _counts(connection)[0] == before[0] + 1

        dispatcher = DurableDispatcher(
            SqlAlchemyDispatchStore(session_factory),
            {
                "ingestion": CeleryIngestionPublisher(app),
                "prediction": CeleryPredictionPublisher(app),
            },
            batch_size=10,
            clock=lambda: NOW,
        )
        assert dispatcher.dispatch_due().target_counts_for("ingestion").enqueued == 1
        with Connection(redis_url) as connection:
            queue = connection.SimpleQueue(INGESTION_QUEUE)
            message = queue.get(block=False)
            try:
                assert message.headers["task"] == INGESTION_TASK_NAME
                assert message.delivery_info["routing_key"] == INGESTION_QUEUE
                command = IngestionCommandV1.model_validate(message.payload[0][0])
                assert command.dispatch_id == dispatch_id
                assert command.run_id == run_id
                assert command.correlation_id == scheduled.correlation_id
                session = _FixtureSession()
                reconciler = ReconcileCurrentCatalog(
                    store=store,
                    retriever=PhivolcsCatalogClient(
                        catalog_url=CATALOG_URL,
                        session=session,
                        max_response_bytes=10_000,
                        connect_timeout_seconds=3,
                        read_timeout_seconds=4,
                        detail_delay_seconds=0,
                    ),
                    diagnostic_reporter=reporter,
                    model_release_id=release_id,
                    history_coverage=history_coverage,
                    now=lambda: NOW,
                    event_reporter=reporter.report_event,
                )
                assert (
                    handle_ingestion_command(
                        command.to_message(),
                        store=store,
                        reconciler=reconciler,
                        logger=logging.getLogger(__name__),
                    )
                    == "succeeded"
                )
                assert len(session.calls) == 3
            finally:
                message.ack()
                queue.close()

        with migrated_engine.connect() as connection:
            run = connection.execute(
                select(ingestion_runs).where(ingestion_runs.c.run_id == run_id)
            ).one()
            revised = connection.execute(
                select(earthquake_event_revisions)
                .where(earthquake_event_revisions.c.source_bulletin_id == "2026_0827_1200_B1")
                .order_by(earthquake_event_revisions.c.revision_number.desc())
            ).first()
            new_revision = connection.execute(
                select(earthquake_event_revisions).where(
                    earthquake_event_revisions.c.source_bulletin_id == "2026_0901_1300_B1"
                )
            ).one()
            job = connection.execute(
                select(prediction_jobs).where(
                    prediction_jobs.c.event_revision_id == new_revision.event_revision_id
                )
            ).one()
            prediction_dispatch = connection.execute(
                select(job_dispatches).where(job_dispatches.c.prediction_job_id == job.job_id)
            ).one()
            after = _counts(connection)
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(ingestion_run_inputs)
                    .where(ingestion_run_inputs.c.run_id == run_id)
                )
                == 3
            )
        assert (run.events_found, run.events_inserted, run.events_revised, run.events_rejected) == (
            3,
            1,
            1,
            1,
        )
        assert run.status == "succeeded"
        assert run.attempt_count == 1
        assert prediction_dispatch.status == "pending"
        assert revised.event_id == original.event_id
        assert revised.event_revision_id != original.event_revision_id
        assert revised.origin == "VOLCANIC"
        assert revised.revision_number == original.revision_number + 1
        assert new_revision.source_time_precision == "second"
        assert job.input_snapshot_hash == feature_snapshot_hash(job.input_snapshot_json)
        assert job.correlation_id == run.correlation_id
        assert after == (before[0] + 1, before[1] + 1, before[2] + 2, before[3] + 1, before[4] + 2)

        assert dispatcher.dispatch_due().target_counts_for("prediction").enqueued >= 1
        found = False
        with Connection(redis_url) as connection:
            queue = connection.SimpleQueue(PREDICTION_QUEUE)
            try:
                while redis_client.llen(PREDICTION_QUEUE):
                    message = queue.get(block=False)
                    try:
                        assert message.headers["task"] == PREDICTION_TASK_NAME
                        assert message.delivery_info["routing_key"] == PREDICTION_QUEUE
                        prediction = PredictionCommandV1.model_validate(message.payload[0][0])
                        if prediction.job_id == job.job_id:
                            assert prediction.dispatch_id == prediction_dispatch.dispatch_id
                            assert prediction.correlation_id == run.correlation_id
                            assert set(message.payload[0][0]) == {
                                "message_version",
                                "dispatch_id",
                                "job_id",
                                "correlation_id",
                            }
                            found = True
                    finally:
                        message.ack()
            finally:
                queue.close()
        assert found
        assert (
            handle_ingestion_command(
                command.to_message(),
                store=store,
                reconciler=reconciler,
                logger=logging.getLogger(__name__),
            )
            == "not_claimed"
        )
        with migrated_engine.connect() as connection:
            assert _counts(connection) == after
            assert connection.execute(
                select(
                    ingestion_runs.c.events_found,
                    ingestion_runs.c.events_inserted,
                    ingestion_runs.c.events_revised,
                    ingestion_runs.c.events_rejected,
                ).where(ingestion_runs.c.run_id == run_id)
            ).one() == (3, 1, 1, 1)
    finally:
        redis_client.delete(INGESTION_QUEUE, PREDICTION_QUEUE)
        redis_client.close()
