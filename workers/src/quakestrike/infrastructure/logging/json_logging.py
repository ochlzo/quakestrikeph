"""Structured JSON logging for worker stdout and stderr."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, TextIO

SAFE_CONTEXT_FIELDS = frozenset(
    {
        "run_id",
        "dispatch_id",
        "correlation_id",
        "worker_execution_id",
        "event_id",
        "event_revision_id",
        "revision_id",
        "input_key",
        "job_id",
        "attempt_id",
        "worker",
        "message_version",
        "message_id",
        "gate",
        "reason",
        "status",
        "exception_type",
        "created",
        "claimed",
        "enqueued",
        "retry_wait",
        "stopped",
        "ingestion_claimed",
        "ingestion_enqueued",
        "ingestion_retry_wait",
        "ingestion_stopped",
        "prediction_claimed",
        "prediction_enqueued",
        "prediction_retry_wait",
        "prediction_stopped",
    }
)
IDENTIFIER_FIELDS = frozenset(
    {
        "run_id",
        "dispatch_id",
        "correlation_id",
        "worker_execution_id",
        "event_id",
        "event_revision_id",
        "revision_id",
        "job_id",
        "attempt_id",
        "worker",
        "message_version",
        "message_id",
    }
)


class JsonFormatter(logging.Formatter):
    """Serialize only the structured fields accepted by the logging adapter."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event_code = getattr(record, "event_code", None)
        if event_code:
            payload["event_code"] = event_code

        context = _safe_context(getattr(record, "context", {}))
        if context:
            payload["context"] = context
            for key in IDENTIFIER_FIELDS:
                if key in context:
                    payload[key] = context[key]

        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def configure_logging(
    service: str,
    *,
    level: str = "INFO",
    stream: TextIO | None = None,
) -> logging.Logger:
    """Configure one service logger with a single structured stream handler."""

    numeric_level = logging.getLevelName(level.upper())
    if not isinstance(numeric_level, int):
        raise ValueError(f"Unknown log level: {level}")

    logger = logging.getLogger(service)
    logger.handlers.clear()
    logger.disabled = False
    logger.setLevel(numeric_level)
    logger.propagate = False

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    logger.addHandler(handler)
    return logger


def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    event_code: str,
    context: Mapping[str, object] | None = None,
) -> None:
    """Emit an event with allow-listed context and no raw payload fields."""

    logger.log(
        level,
        message,
        extra={
            "event_code": event_code,
            "context": _safe_context(context or {}),
        },
    )


def log_exception_event(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    event_code: str,
    error: BaseException,
    context: Mapping[str, object] | None = None,
) -> None:
    """Emit a structured failure without serializing exception text or traces."""

    safe_context = dict(context or {})
    safe_context["exception_type"] = safe_exception_type(error)
    log_event(
        logger,
        level,
        message,
        event_code=event_code,
        context=safe_context,
    )


def safe_exception_type(error: BaseException) -> str:
    """Return only a bounded class name suitable for operational diagnostics."""

    name = type(error).__name__
    if name and len(name) <= 100 and name.isidentifier():
        return name
    return "UnknownError"


def _safe_context(context: Mapping[str, object]) -> dict[str, str | int | float | bool]:
    safe: dict[str, str | int | float | bool] = {}
    for key, value in context.items():
        if key not in SAFE_CONTEXT_FIELDS or value is None:
            continue
        if isinstance(value, bool | int | float):
            safe[key] = value
        else:
            safe[key] = str(value)[:500]
    return safe
