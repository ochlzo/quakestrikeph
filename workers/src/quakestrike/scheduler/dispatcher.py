"""Long-lived PostgreSQL-to-Redis ingestion dispatcher entry point."""

from __future__ import annotations

import logging
import signal
from threading import Event

from quakestrike.application.ingestion_dispatch import (
    DispatchBatchResult,
    DurableIngestionDispatcher,
)
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.database.ingestion_dispatch import (
    SqlAlchemyIngestionDispatchStore,
)
from quakestrike.infrastructure.logging.json_logging import log_event, log_exception_event
from quakestrike.infrastructure.queues.celery_app import create_celery_app
from quakestrike.infrastructure.queues.ingestion_publisher import CeleryIngestionPublisher
from quakestrike.infrastructure.settings import Settings
from quakestrike.runtime import run_service


def run_dispatch_loop(
    dispatcher: DurableIngestionDispatcher,
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
            _log_scan_result(logger, result)

        if stop_event.wait(poll_interval_seconds):
            return


def run_dispatcher(settings: Settings, *, stop_event: Event | None = None) -> int:
    """Construct the durable dispatcher and keep scanning until a signal arrives."""

    shutdown = stop_event if stop_event is not None else Event()
    logger = logging.getLogger("scheduler-dispatcher")
    engine = create_database_engine(settings.database_url)
    previous_handlers = _install_shutdown_handlers(shutdown)
    try:
        app = create_celery_app(settings)
        store = SqlAlchemyIngestionDispatchStore(
            create_session_factory(engine),
            lease_seconds=settings.dispatch_lease_seconds,
            retry_delays_seconds=settings.retry_delays_seconds,
        )
        dispatcher = DurableIngestionDispatcher(
            store,
            CeleryIngestionPublisher(app),
            batch_size=settings.dispatcher_batch_size,
        )
        run_dispatch_loop(
            dispatcher,
            poll_interval_seconds=settings.dispatcher_poll_interval_seconds,
            stop_event=shutdown,
            logger=logger,
        )
    finally:
        _restore_shutdown_handlers(previous_handlers)
        engine.dispose()
    return 0


def main() -> int:
    return run_service("scheduler-dispatcher", runtime=run_dispatcher)


def _log_scan_result(logger: logging.Logger, result: DispatchBatchResult) -> None:
    log_event(
        logger,
        logging.INFO,
        "dispatcher scan completed",
        event_code="dispatcher_scan_completed",
        context={
            "status": "completed",
            "claimed": result.claimed,
            "enqueued": result.enqueued,
            "retry_wait": result.retry_wait,
            "stopped": result.stopped,
        },
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
