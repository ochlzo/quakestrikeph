from __future__ import annotations

import io
import json
import logging

from quakestrike.infrastructure.logging.json_logging import (
    configure_logging,
    log_event,
    log_exception_event,
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
            "source_payload": "private-source-row",
            "model_weights": "private-model-weights",
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
    assert "private-source-row" not in output.getvalue()
    assert "private-model-weights" not in output.getvalue()


def test_exception_logging_keeps_type_and_redacts_exception_text() -> None:
    output = io.StringIO()
    logger = configure_logging("scheduler-dispatcher", level="INFO", stream=output)

    log_exception_event(
        logger,
        logging.ERROR,
        "dispatcher scan failed",
        event_code="dispatcher_scan_failed",
        error=RuntimeError(
            "redis://worker:secret@example.invalid/0?password=must-not-cross-the-boundary"
        ),
        context={"dispatch_id": "dispatch-123"},
    )

    record = json.loads(output.getvalue())
    assert record["event_code"] == "dispatcher_scan_failed"
    assert record["context"] == {
        "dispatch_id": "dispatch-123",
        "exception_type": "RuntimeError",
    }
    assert "secret" not in output.getvalue()
    assert "password" not in output.getvalue()


def test_json_formatter_does_not_emit_exception_traces() -> None:
    output = io.StringIO()
    logger = configure_logging("scheduler-beat", level="INFO", stream=output)

    try:
        raise RuntimeError("password=must-not-cross-the-boundary")
    except RuntimeError:
        logger.error("scheduled tick failed", exc_info=True)

    record = json.loads(output.getvalue())
    assert record["message"] == "scheduled tick failed"
    assert "exception" not in record
    assert "password" not in output.getvalue()
