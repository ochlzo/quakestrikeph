"""Long-lived PostgreSQL-to-Redis durable dispatcher entry point."""

from __future__ import annotations

import logging
import os
import signal
import tempfile
from pathlib import Path
from threading import Event

from quakestrike.application.dispatch import DispatchBatchResult, DurableDispatcher
from quakestrike.infrastructure.database.dispatch import SqlAlchemyDispatchStore
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.logging.json_logging import log_event, log_exception_event
from quakestrike.infrastructure.queues.celery_app import create_celery_app
from quakestrike.infrastructure.queues.ingestion_publisher import CeleryIngestionPublisher
from quakestrike.infrastructure.queues.prediction_publisher import CeleryPredictionPublisher
from quakestrike.infrastructure.settings import Settings
from quakestrike.runtime import run_service

SCAN_HEALTH_MARKER = Path(tempfile.gettempdir()) / "quakestrike-dispatcher-scan"


def run_dispatch_loop(
    dispatcher: DurableDispatcher,
    *,
    poll_interval_seconds: int,
    stop_event: Event,
    logger: logging.Logger,
) -> None:
    """Scan immediately, then wait between scans until shutdown is requested."""

    if poll_interval_seconds <= 0:
        raise ValueError("Dispatcher poll interval must be positive.")

    while not stop_event.is_set():
        try:
            result = dispatcher.dispatch_due()
        except Exception as error:
            log_exception_event(
                logger,
                logging.ERROR,
                "dispatcher scan failed",
                event_code="dispatcher_scan_failed",
                error=error,
            )
        else:
            SCAN_HEALTH_MARKER.write_text(str(os.getpid()), encoding="ascii")
            _log_scan_result(logger, result)

        if stop_event.wait(poll_interval_seconds):
            return


def run_dispatcher(settings: Settings, *, stop_event: Event | None = None) -> int:
    """Construct the durable dispatcher and keep scanning until a signal arrives."""

    shutdown = stop_event if stop_event is not None else Event()
    logger = logging.getLogger("scheduler-dispatcher")
    SCAN_HEALTH_MARKER.unlink(missing_ok=True)
    engine = create_database_engine(settings.database_url)
    previous_handlers = _install_shutdown_handlers(shutdown)
    try:
        app = create_celery_app(settings)
        store = SqlAlchemyDispatchStore(
            create_session_factory(engine),
            lease_seconds=settings.dispatch_lease_seconds,
            retry_delays_seconds=settings.retry_delays_seconds,
        )
        dispatcher = DurableDispatcher(
            store,
            {
                "ingestion": CeleryIngestionPublisher(app),
                "prediction": CeleryPredictionPublisher(app),
            },
            batch_size=settings.dispatcher_batch_size,
        )
        run_dispatch_loop(
            dispatcher,
            poll_interval_seconds=settings.dispatcher_poll_interval_seconds,
            stop_event=shutdown,
            logger=logger,
        )
    finally:
        SCAN_HEALTH_MARKER.unlink(missing_ok=True)
        _restore_shutdown_handlers(previous_handlers)
        engine.dispose()
    return 0


def main() -> int:
    return run_service("scheduler-dispatcher", runtime=run_dispatcher)


def _log_scan_result(logger: logging.Logger, result: DispatchBatchResult) -> None:
    context: dict[str, object] = {
        "status": "completed",
        "claimed": result.claimed,
        "enqueued": result.enqueued,
        "retry_wait": result.retry_wait,
        "stopped": result.stopped,
    }
    for target_kind, counts in result.target_counts:
        context.update(
            {
                f"{target_kind}_claimed": counts.claimed,
                f"{target_kind}_enqueued": counts.enqueued,
                f"{target_kind}_retry_wait": counts.retry_wait,
                f"{target_kind}_stopped": counts.stopped,
            }
        )
    log_event(
        logger,
        logging.INFO,
        "dispatcher scan completed",
        event_code="dispatcher_scan_completed",
        context=context,
    )


def _install_shutdown_handlers(stop_event: Event) -> dict[int, object]:
    previous: dict[int, object] = {}

    def request_shutdown(_signum, _frame) -> None:  # type: ignore[no-untyped-def]
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, request_shutdown)
        except (OSError, ValueError):
            continue
    return previous


def _restore_shutdown_handlers(previous: dict[int, object]) -> None:
    for signum, handler in previous.items():
        try:
            signal.signal(signum, handler)  # type: ignore[arg-type]
        except (OSError, ValueError):
            continue


if __name__ == "__main__":
    raise SystemExit(main())
