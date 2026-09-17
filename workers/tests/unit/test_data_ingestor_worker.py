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


def test_valid_command_reconciles_its_database_run(caplog) -> None:
    store = _CommandStore(matches=True)
    reconciler = _Reconciler(ReconciliationRunResult(status="succeeded", claimed=True))

    result = handle_ingestion_command(
        _payload(), store=store, reconciler=reconciler, logger=logging.getLogger("test-ingestor")
    )

    assert result == "succeeded"
    assert store.checked == [(DISPATCH_ID, RUN_ID, CORRELATION_ID)]
    assert reconciler.run_ids == [RUN_ID]


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


def test_command_with_mismatched_durable_ids_is_rejected(caplog) -> None:
    store = _CommandStore(matches=False)
    reconciler = _Reconciler(ReconciliationRunResult(status="succeeded", claimed=True))

    result = handle_ingestion_command(
        _payload(), store=store, reconciler=reconciler, logger=logging.getLogger("test-ingestor")
    )

    assert result == "rejected"
    assert store.checked == [(DISPATCH_ID, RUN_ID, CORRELATION_ID)]
    assert reconciler.run_ids == []


def test_duplicate_delivery_that_cannot_claim_is_a_safe_no_op(caplog) -> None:
    store = _CommandStore(matches=True)
    reconciler = _Reconciler(ReconciliationRunResult(status="not_claimed", claimed=False))

    result = handle_ingestion_command(
        _payload(), store=store, reconciler=reconciler, logger=logging.getLogger("test-ingestor")
    )

    assert result == "not_claimed"
    assert reconciler.run_ids == [RUN_ID]


def test_ingestor_app_registers_the_routed_task_with_the_identifier_only_payload() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id="00000000-0000-0000-0000-000000000004",
    )
    received = []
    app = create_ingestor_app(settings, command_handler=lambda payload: received.append(payload))

    app.tasks[INGESTION_TASK_NAME].run(_payload())

    assert received == [_payload()]
    assert app.tasks[INGESTION_TASK_NAME].acks_late is True
    assert app.tasks[INGESTION_TASK_NAME].reject_on_worker_lost is True
    assert app.tasks[INGESTION_TASK_NAME].acks_on_failure_or_timeout is False


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
