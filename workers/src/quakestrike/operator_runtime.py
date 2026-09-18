"""Read-only worker health and explicit immediate polling."""

from __future__ import annotations

import os
import socket
import time

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from quakestrike.application.scheduling import ScheduleIngestionPoll
from quakestrike.application.startup import evaluate_startup_gates
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.database.migration_state import AlembicMigrationStateGate
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.health import (
    PostgresConnectivityHealthCheck,
    RedisConnectivityHealthCheck,
)
from quakestrike.infrastructure.queues.celery_app import INGESTION_QUEUE, create_celery_app
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import (
    ConfiguredModelReleaseVerifier,
    phase_one_startup_gates,
)
from quakestrike.operator_output import print_json
from quakestrike.scheduler.dispatcher import SCAN_HEALTH_MARKER


def worker_health(action: str) -> int:
    try:
        settings = Settings()
        connected = all(
            gate.check().ready
            for gate in (
                PostgresConnectivityHealthCheck(settings),
                RedisConnectivityHealthCheck(settings),
                AlembicMigrationStateGate(settings),
            )
        )
        if action == "health-dispatcher":
            active = dispatcher_running(settings)
        elif action == "health-ingestor":
            active = ingestor_consuming(settings, local_only=True)
        else:
            active = evaluate_startup_gates(phase_one_startup_gates(settings)).ready
        ready = connected and active
        print_json({"action": action, "status": "healthy" if ready else "unhealthy"})
        return 0 if ready else 2
    except Exception:
        print_json({"action": action, "status": "unhealthy"})
        return 2


def immediate_poll() -> int:
    """Request one manual poll only after the read-only runtime gates pass."""

    try:
        settings = Settings()
        report = evaluate_startup_gates(phase_one_startup_gates(settings))
        if not report.ready:
            print_json(
                {
                    "action": "poll-now",
                    "status": "not_ready",
                    "failed_gate_names": list(report.failed_gate_names),
                }
            )
            return 2
        if not consumers_ready(settings):
            print_json(
                {"action": "poll-now", "status": "not_ready", "reason": "consumer_unhealthy"}
            )
            return 2
        engine = create_database_engine(settings.database_url)
        try:
            store = SqlAlchemyIngestionTransactions(
                create_session_factory(engine),
                model_release_verifier=ConfiguredModelReleaseVerifier(settings),
            )
            result = ScheduleIngestionPoll(store, trigger_type="manual").execute()
            state = store.get_ingestion_run(result.run_id)
            if state is None:
                raise ValueError("Created run is unavailable.")
        finally:
            engine.dispose()
        print_json(
            {
                "action": "poll-now",
                "status": "created" if result.created else "reused",
                "run_id": str(result.run_id),
                "dispatch_id": str(result.dispatch_id),
                "trigger_type": state.trigger_type,
            }
        )
        return 0
    except (ValidationError, SQLAlchemyError, OSError, ValueError):
        print_json(
            {
                "action": "poll-now",
                "status": "failed",
                "reason": "poll request could not be completed safely",
            }
        )
        return 2


def ingestor_consuming(settings: Settings, *, local_only: bool = False) -> bool:
    app = create_celery_app(settings)
    destination = f"data-ingestor@{socket.gethostname()}" if local_only else None
    inspector = app.control.inspect(destination=[destination] if destination else None, timeout=3)
    queues = inspector.active_queues() or {}
    return any(
        worker.startswith("data-ingestor@")
        and (not local_only or worker == destination)
        and any(queue.get("name") == INGESTION_QUEUE for queue in worker_queues)
        for worker, worker_queues in queues.items()
    )


def consumers_ready(settings: Settings) -> bool:
    return dispatcher_running(settings) and ingestor_consuming(settings)


def dispatcher_running(settings: Settings) -> bool:
    try:
        if time.time() - SCAN_HEALTH_MARKER.stat().st_mtime > max(
            20, settings.dispatcher_poll_interval_seconds * 3
        ):
            return False
        pid = int(SCAN_HEALTH_MARKER.read_text(encoding="ascii"))
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False
