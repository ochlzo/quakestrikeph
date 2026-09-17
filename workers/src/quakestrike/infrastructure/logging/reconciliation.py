"""Structured logging adapter for reconciliation row diagnostics."""

from __future__ import annotations

import logging

from quakestrike.application.reconciliation import (
    ReconciliationDiagnostic,
    ReconciliationDiagnosticReporter,
)
from quakestrike.infrastructure.logging.json_logging import log_event


class StructuredReconciliationDiagnosticReporter(ReconciliationDiagnosticReporter):
    """Emit only safe diagnostic codes and durable reconciliation identifiers."""

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
                "input_key": diagnostic.input_key,
            },
        )
