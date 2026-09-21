from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from uuid import UUID

from quakestrike.application.dispatch import (
    DispatchBatchResult,
    DispatchOutcome,
    DispatchTargetCounts,
    IngestionDispatch,
    PredictionDispatch,
)
from quakestrike.infrastructure.logging.json_logging import configure_logging
from quakestrike.scheduler import dispatcher as dispatcher_module
from quakestrike.scheduler.dispatcher import run_dispatch_loop


class StopAfterWait:
    def __init__(self) -> None:
        self.waits: list[float] = []

    def is_set(self) -> bool:
        return False

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(timeout if timeout is not None else -1)
        return True


class OneScanDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    def dispatch_due(self) -> DispatchBatchResult:
        self.calls += 1
        dispatch = IngestionDispatch(
            dispatch_id=UUID("11111111-1111-4111-8111-111111111111"),
            run_id=UUID("22222222-2222-4222-8222-222222222222"),
            correlation_id=UUID("33333333-3333-4333-8333-333333333333"),
        )
        return DispatchBatchResult(
            claimed=1,
            enqueued=1,
            retry_wait=0,
            stopped=0,
            target_counts=(
                ("ingestion", DispatchTargetCounts(claimed=1, enqueued=1)),
                ("prediction", DispatchTargetCounts()),
            ),
            outcomes=(DispatchOutcome(dispatch, "enqueued"),),
        )


def test_dispatcher_loop_scans_then_waits_at_the_configured_interval() -> None:
    stop_event = StopAfterWait()
    dispatcher = OneScanDispatcher()

    run_dispatch_loop(
        dispatcher,
        poll_interval_seconds=5,
        stop_event=stop_event,
        logger=logging.getLogger("test-dispatcher"),
    )

    assert dispatcher.calls == 1
    assert stop_event.waits == [5]


def test_dispatcher_marker_only_follows_a_successful_scan(monkeypatch, tmp_path: Path) -> None:
    marker = tmp_path / "scan"
    monkeypatch.setattr(dispatcher_module, "SCAN_HEALTH_MARKER", marker)
    run_dispatch_loop(
        OneScanDispatcher(),
        poll_interval_seconds=5,
        stop_event=StopAfterWait(),  # type: ignore[arg-type]
        logger=logging.getLogger("test-dispatcher"),
    )
    assert marker.read_text(encoding="ascii") == str(os.getpid())
    marker.unlink()

    class FailingDispatcher:
        def dispatch_due(self) -> DispatchBatchResult:
            raise RuntimeError("scan failed")

    run_dispatch_loop(
        FailingDispatcher(),  # type: ignore[arg-type]
        poll_interval_seconds=5,
        stop_event=StopAfterWait(),  # type: ignore[arg-type]
        logger=logging.getLogger("test-dispatcher"),
    )
    assert not marker.exists()


def test_dispatcher_scan_logging_labels_target_counts() -> None:
    output = io.StringIO()
    logger = configure_logging("scheduler-dispatcher", level="INFO", stream=output)
    stop_event = StopAfterWait()

    run_dispatch_loop(
        OneScanDispatcher(),
        poll_interval_seconds=5,
        stop_event=stop_event,
        logger=logger,
    )

    assert '"ingestion_claimed":1' in output.getvalue()
    assert '"prediction_claimed":0' in output.getvalue()
    assert '"event_code":"dispatch_enqueued"' in output.getvalue()
    assert '"dispatch_id":"11111111-1111-4111-8111-111111111111"' in output.getvalue()
    assert '"run_id":"22222222-2222-4222-8222-222222222222"' in output.getvalue()
    assert '"correlation_id":"33333333-3333-4333-8333-333333333333"' in output.getvalue()


def test_dispatcher_retry_log_has_target_ids_and_bounded_error() -> None:
    error = RuntimeError("redis://worker:secret@example.invalid/0?password=must-not-log")
    dispatch = PredictionDispatch(
        dispatch_id=UUID("44444444-4444-4444-8444-444444444444"),
        job_id=UUID("55555555-5555-4555-8555-555555555555"),
        correlation_id=UUID("66666666-6666-4666-8666-666666666666"),
    )

    class RetryDispatcher:
        def dispatch_due(self) -> DispatchBatchResult:
            return DispatchBatchResult(
                claimed=1,
                enqueued=0,
                retry_wait=1,
                stopped=0,
                outcomes=(DispatchOutcome(dispatch, "retry_wait", error),),
            )

    output = io.StringIO()
    run_dispatch_loop(
        RetryDispatcher(),  # type: ignore[arg-type]
        poll_interval_seconds=5,
        stop_event=StopAfterWait(),  # type: ignore[arg-type]
        logger=configure_logging("scheduler-dispatcher", level="INFO", stream=output),
    )

    log = output.getvalue()
    assert '"event_code":"dispatch_retry_wait"' in log
    assert '"dispatch_id":"44444444-4444-4444-8444-444444444444"' in log
    assert '"job_id":"55555555-5555-4555-8555-555555555555"' in log
    assert '"correlation_id":"66666666-6666-4666-8666-666666666666"' in log
    assert '"exception_type":"RuntimeError"' in log
    assert "secret" not in log
    assert "password" not in log


def test_dispatcher_scan_failure_uses_structured_redacted_logging() -> None:
    class FailingDispatcher:
        def dispatch_due(self) -> DispatchBatchResult:
            raise RuntimeError("redis://worker:secret@example.invalid/0?password=must-not-log")

    output = io.StringIO()
    logger = configure_logging("scheduler-dispatcher", level="INFO", stream=output)
    stop_event = StopAfterWait()

    run_dispatch_loop(
        FailingDispatcher(),  # type: ignore[arg-type]
        poll_interval_seconds=5,
        stop_event=stop_event,  # type: ignore[arg-type]
        logger=logger,
    )

    assert '"event_code":"dispatcher_scan_failed"' in output.getvalue()
    assert '"exception_type":"RuntimeError"' in output.getvalue()
    assert "secret" not in output.getvalue()
    assert "password" not in output.getvalue()
