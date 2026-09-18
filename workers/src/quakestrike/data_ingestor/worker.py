"""Data Ingestor queue boundary and process entry point."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Protocol
from uuid import UUID

from celery import Celery
from celery.exceptions import Reject
from pydantic import ValidationError

from quakestrike.application.reconciliation import (
    ReconcileCurrentCatalog,
    ReconciliationRunResult,
)
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.logging.json_logging import log_event, log_exception_event
from quakestrike.infrastructure.logging.reconciliation import (
    StructuredReconciliationDiagnosticReporter,
)
from quakestrike.infrastructure.phivolcs.client import PhivolcsCatalogClient
from quakestrike.infrastructure.phivolcs.session import create_phivolcs_session
from quakestrike.infrastructure.queues.celery_app import (
    INGESTION_QUEUE,
    INGESTION_TASK_NAME,
    create_celery_app,
)
from quakestrike.infrastructure.queues.contracts import parse_ingestion_command
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import ConfiguredModelReleaseVerifier
from quakestrike.runtime import run_service


class IngestionCommandStore(Protocol):
    """Verify that queue identifiers describe one durable ingestion dispatch."""

    def ingestion_command_matches(
        self, dispatch_id: UUID, run_id: UUID, correlation_id: UUID
    ) -> bool: ...


class CatalogReconciler(Protocol):
    """Run the existing fenced current-catalog workflow."""

    def execute(self, run_id: UUID) -> ReconciliationRunResult: ...


def handle_ingestion_command(
    payload: object,
    *,
    store: IngestionCommandStore,
    reconciler: CatalogReconciler,
    logger: logging.Logger,
) -> str:
    """Validate one queue delivery and reconcile only its matching durable run."""

    if not isinstance(payload, Mapping):
        return _reject_invalid_command(logger)
    try:
        command = parse_ingestion_command(payload)
    except ValidationError:
        return _reject_invalid_command(logger)

    context = command.to_message()
    if not store.ingestion_command_matches(
        command.dispatch_id,
        command.run_id,
        command.correlation_id,
    ):
        log_event(
            logger,
            logging.WARNING,
            "Ingestion command identifiers do not match durable work.",
            event_code="ingestion_command_mismatch",
            context=context,
        )
        return "rejected"

    result = reconciler.execute(command.run_id)
    log_event(
        logger,
        logging.INFO,
        "Ingestion command processing finished.",
        event_code="ingestion_command_finished",
        context=context | {"status": result.status, "claimed": result.claimed},
    )
    return result.status


def _reject_invalid_command(logger: logging.Logger) -> str:
    log_event(
        logger,
        logging.WARNING,
        "Ingestion command validation failed.",
        event_code="ingestion_command_invalid",
        context={"status": "rejected"},
    )
    return "rejected"


def process_ingestion_delivery(
    settings: Settings,
    payload: object,
    *,
    logger: logging.Logger | None = None,
) -> str:
    """Build per-delivery adapters without sharing database connections across worker forks."""

    task_logger = logger or logging.getLogger("data-ingestor")
    engine = create_database_engine(settings.database_url)
    session = create_phivolcs_session()
    try:
        store = SqlAlchemyIngestionTransactions(
            create_session_factory(engine),
            model_release_verifier=ConfiguredModelReleaseVerifier(settings),
        )
        reporter = StructuredReconciliationDiagnosticReporter(task_logger)
        reconciler = ReconcileCurrentCatalog(
            store=store,
            retriever=PhivolcsCatalogClient(
                catalog_url=settings.phivolcs_catalog_url,
                session=session,
                max_response_bytes=settings.max_response_bytes,
                connect_timeout_seconds=settings.http_connect_timeout_seconds,
                read_timeout_seconds=settings.http_read_timeout_seconds,
                detail_delay_seconds=settings.detail_request_delay_seconds,
            ),
            diagnostic_reporter=reporter,
            model_release_id=settings.model_release_id,
            event_reporter=reporter.report_event,
        )
        return handle_ingestion_command(
            payload,
            store=store,
            reconciler=reconciler,
            logger=task_logger,
        )
    finally:
        session.close()
        engine.dispose()


def create_ingestor_app(
    settings: Settings,
    *,
    command_handler: Callable[[object], object] | None = None,
) -> Celery:
    """Create the ingestion Celery app and register its public queue task."""

    app = create_celery_app(settings)
    handler = command_handler or (lambda payload: process_ingestion_delivery(settings, payload))

    @app.task(
        name=INGESTION_TASK_NAME,
        acks_late=True,
        reject_on_worker_lost=True,
        acks_on_failure_or_timeout=False,
    )
    def process_ingestion(payload: object) -> object:
        return execute_ingestion_task(
            payload,
            command_handler=handler,
            logger=logging.getLogger("data-ingestor"),
        )

    return app


def execute_ingestion_task(
    payload: object,
    *,
    command_handler: Callable[[object], object],
    logger: logging.Logger,
) -> object:
    """Keep unexpected exception details out of Celery's task-failure diagnostics."""

    try:
        return command_handler(payload)
    except Exception as error:
        log_exception_event(
            logger,
            logging.ERROR,
            "Ingestion command processing failed.",
            event_code="ingestion_command_processing_failed",
            error=error,
            context=_validated_command_context(payload),
        )
        raise Reject("Ingestion command processing failed.", requeue=True) from None


def _validated_command_context(payload: object) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        return {}
    try:
        return parse_ingestion_command(payload).to_message()
    except ValidationError:
        return {}


def run_ingestor(settings: Settings) -> int:
    """Start the one-slot ingestion worker. Celery handles graceful process shutdown."""

    app = create_ingestor_app(settings)
    app.worker_main(
        [
            "worker",
            "--loglevel",
            settings.log_level,
            "--queues",
            INGESTION_QUEUE,
            "--concurrency",
            str(settings.ingestor_concurrency),
            "--hostname",
            "data-ingestor@%h",
        ]
    )
    return 0


def main() -> int:
    return run_service("data-ingestor", runtime=run_ingestor)


if __name__ == "__main__":
    raise SystemExit(main())
