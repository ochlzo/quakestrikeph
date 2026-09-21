"""Structured logging adapter for reconciliation outcomes."""

from __future__ import annotations

import logging

from quakestrike.application.persistence import EventTransactionResult, RunClaim
from quakestrike.application.reconciliation import (
    ReconciliationDiagnostic,
    ReconciliationDiagnosticReporter,
)
from quakestrike.infrastructure.logging.json_logging import log_event


class StructuredReconciliationReporter(ReconciliationDiagnosticReporter):
    """Emit safe row diagnostics and committed event identifiers."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def report(self, diagnostic: ReconciliationDiagnostic) -> None:
        log_event(
            self._logger,
            logging.WARNING,
            "Reconciliation row diagnostic.",
            event_code=diagnostic.code,
            context={
                "run_id": diagnostic.run_id,
                "worker_execution_id": diagnostic.worker_execution_id,
                "correlation_id": diagnostic.correlation_id,
                "input_key": diagnostic.input_key,
            },
        )

    def report_event(self, claim: RunClaim, result: EventTransactionResult) -> None:
        """Log committed event work using durable identifiers only."""

        status = (
            "inserted"
            if result.event_created
            else "revised"
            if result.revision_created
            else "unchanged"
        )
        log_event(
            self._logger,
            logging.INFO,
            "Event reconciliation committed.",
            event_code="event_reconciled",
            context={
                "run_id": claim.run_id,
                "worker_execution_id": claim.worker_execution_id,
                "correlation_id": claim.correlation_id,
                "event_id": result.event_id,
                "event_revision_id": result.event_revision_id,
                "job_id": result.prediction_job_id,
                "dispatch_id": result.dispatch_id,
                "status": status,
            },
        )
