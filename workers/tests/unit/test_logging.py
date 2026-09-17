from __future__ import annotations

import io
import json
import logging
from uuid import uuid4

from quakestrike.application.reconciliation import ReconciliationDiagnostic
from quakestrike.infrastructure.logging.json_logging import configure_logging, log_event
from quakestrike.infrastructure.logging.reconciliation import (
    StructuredReconciliationDiagnosticReporter,
)


def test_structured_logging_emits_json_with_operational_identifiers() -> None:
    output = io.StringIO()
    logger = configure_logging("data-ingestor", level="INFO", stream=output)

    log_event(
        logger,
        logging.INFO,
        "ingestion command accepted",
        event_code="queue_command_accepted",
        context={
            "run_id": "run-123",
            "dispatch_id": "dispatch-123",
            "correlation_id": "correlation-123",
            "raw_html": "must-not-be-logged",
        },
    )

    record = json.loads(output.getvalue())
    assert record["service"] == "data-ingestor"
    assert record["event_code"] == "queue_command_accepted"
    assert record["run_id"] == "run-123"
    assert record["dispatch_id"] == "dispatch-123"
    assert record["correlation_id"] == "correlation-123"
    assert "raw_html" not in record
    assert "must-not-be-logged" not in output.getvalue()


def test_reconciliation_diagnostic_logger_includes_run_and_input_correlation() -> None:
    output = io.StringIO()
    correlation_id = uuid4()
    reporter = StructuredReconciliationDiagnosticReporter(
        configure_logging("data-ingestor", level="INFO", stream=output)
    )

    reporter.report(
        ReconciliationDiagnostic(
            run_id=uuid4(),
            worker_execution_id=uuid4(),
            correlation_id=correlation_id,
            input_key="row:abc123",
            code="DETAIL_FETCH_FAILED",
        )
    )

    record = json.loads(output.getvalue())
    assert record["event_code"] == "DETAIL_FETCH_FAILED"
    assert record["context"]["input_key"] == "row:abc123"
    assert record["context"]["correlation_id"] == str(correlation_id)
    assert "run_id" in record["context"]
