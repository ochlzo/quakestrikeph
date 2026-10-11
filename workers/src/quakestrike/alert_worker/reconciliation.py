"""Reconciliation entry point, independent from submission queue consumption."""

import logging
import os
import signal
import tempfile
from pathlib import Path
from threading import Event

from quakestrike.application.alert_reconciliation import AlertReconciliation
from quakestrike.infrastructure.alert_readiness import (
    configured_alert_providers,
    reconciliation_startup_gates,
)
from quakestrike.infrastructure.database.alerts import SqlAlchemyAlertStore
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.logging.json_logging import log_event
from quakestrike.runtime import run_service

SCAN_HEALTH_MARKER = Path(tempfile.gettempdir()) / "quakestrike-alert-reconciliation-scan"


def run_reconciliation(settings, *, stop_event=None):
    if not settings.alert_delivery_enabled:
        raise ValueError("Alert reconciliation runtime is disabled.")
    provider = configured_alert_providers(settings, channels=("sms",))["sms"]
    shutdown = stop_event if stop_event is not None else Event()
    logger = logging.getLogger("alert-reconciliation")
    engine = create_database_engine(settings.database_url, statement_timeout_ms=5000)
    previous_handlers = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, lambda *_: shutdown.set())
    SCAN_HEALTH_MARKER.unlink(missing_ok=True)

    def report(candidate, result, outcome):
        context = {"status": outcome, "provider": "iprog"}
        if candidate is not None:
            context.update(
                attempt_id=str(candidate.delivery_attempt_id),
                alert_job_id=str(candidate.alert_job_id),
                correlation_id=str(candidate.correlation_id),
            )
        if result is not None:
            context.update(result.evidence)
            context["reason"] = result.error_code
        log_event(
            logger,
            logging.INFO,
            "Alert reconciliation processed.",
            event_code="alert_reconciliation_processed",
            context=context,
        )

    runtime = AlertReconciliation(
        SqlAlchemyAlertStore(create_session_factory(engine)), provider, report=report
    )
    try:
        while not shutdown.is_set():
            result = runtime.execute(limit=settings.alert_reconciliation_batch_size)
            if result["healthy"]:
                SCAN_HEALTH_MARKER.write_text(str(os.getpid()), encoding="ascii")
            if shutdown.wait(settings.alert_reconciliation_interval_seconds):
                break
    finally:
        engine.dispose()
        SCAN_HEALTH_MARKER.unlink(missing_ok=True)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return 0


def main():
    return run_service(
        "alert-reconciliation",
        runtime=run_reconciliation,
        gate_factory=reconciliation_startup_gates,
    )
