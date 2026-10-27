from __future__ import annotations

import logging
from uuid import UUID

import pytest
from celery.exceptions import Reject

from quakestrike.application.reconciliation import ReconciliationRunResult
from quakestrike.data_ingestor.worker import (
    create_ingestor_app,
    execute_ingestion_task,
    handle_ingestion_command,
)
from quakestrike.infrastructure.queues.celery_app import INGESTION_TASK_NAME
from quakestrike.infrastructure.settings import Settings

DISPATCH_ID = UUID("00000000-0000-0000-0000-000000000001")
RUN_ID = UUID("00000000-0000-0000-0000-000000000002")
CORRELATION_ID = UUID("00000000-0000-0000-0000-000000000003")
MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000004")


class _CommandStore:
    def __init__(self, matches: bool) -> None:
        self.matches = matches
        self.checked = []

    def ingestion_command_matches(self, dispatch_id, run_id, correlation_id) -> bool:
        self.checked.append((dispatch_id, run_id, correlation_id))
        return self.matches


class _Reconciler:
    def __init__(self, result: ReconciliationRunResult) -> None:
        self.result = result
        self.run_ids = []

    def execute(self, run_id):
        self.run_ids.append(run_id)
        return self.result


def _payload() -> dict[str, object]:
    return {
        "message_version": 1,
        "dispatch_id": str(DISPATCH_ID),
        "run_id": str(RUN_ID),
        "correlation_id": str(CORRELATION_ID),
    }


def test_malformed_command_is_rejected_without_database_or_reconciliation_work(caplog) -> None:
    store = _CommandStore(matches=True)
    reconciler = _Reconciler(ReconciliationRunResult(status="succeeded", claimed=True))
    payload = _payload() | {"message_version": 2}

    result = handle_ingestion_command(
        payload, store=store, reconciler=reconciler, logger=logging.getLogger("test-ingestor")
    )

    assert result == "rejected"
    assert store.checked == []
    assert reconciler.run_ids == []


def test_ingestor_task_logs_the_broker_message_id(caplog) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id="00000000-0000-0000-0000-000000000005",
    )
    payloads = []
    app = create_ingestor_app(
        settings, command_handler=lambda payload: payloads.append(payload) or "succeeded"
    )
    task = app.tasks[INGESTION_TASK_NAME]
    assert task.acks_late is True
    assert task.reject_on_worker_lost is True
    assert task.acks_on_failure_or_timeout is False

    with caplog.at_level(logging.INFO, logger="data-ingestor"):
        result = task.apply(args=[_payload()], task_id=str(MESSAGE_ID))

    assert result.successful()
    assert payloads == [_payload()]
    received = next(
        record for record in caplog.records if record.event_code == "ingestion_command_received"
    )
    assert received.context == {
        "message_version": 1,
        "message_id": str(MESSAGE_ID),
        "dispatch_id": str(DISPATCH_ID),
        "run_id": str(RUN_ID),
        "correlation_id": str(CORRELATION_ID),
    }


def test_ingestor_task_replaces_unexpected_error_details_with_a_safe_failure(caplog) -> None:
    def fail(_payload: object) -> None:
        raise RuntimeError("database password must-not-leak")

    with pytest.raises(Reject) as rejected:
        execute_ingestion_task(
            _payload(),
            command_handler=fail,
            logger=logging.getLogger("data-ingestor"),
        )

    assert rejected.value.requeue is True
    assert rejected.value.reason == "Ingestion command processing failed."
    assert "must-not-leak" not in caplog.text
    assert caplog.records[-1].context == {
        "message_version": 1,
        "dispatch_id": str(DISPATCH_ID),
        "run_id": str(RUN_ID),
        "correlation_id": str(CORRELATION_ID),
        "exception_type": "RuntimeError",
    }
