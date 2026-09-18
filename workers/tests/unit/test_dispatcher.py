from __future__ import annotations

import io
import logging

from quakestrike.application.dispatch import (
    DispatchBatchResult,
    DispatchTargetCounts,
)
from quakestrike.infrastructure.logging.json_logging import configure_logging
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
        return DispatchBatchResult(
            claimed=1,
            enqueued=1,
            retry_wait=0,
            stopped=0,
            target_counts=(
                ("ingestion", DispatchTargetCounts(claimed=1, enqueued=1)),
                ("prediction", DispatchTargetCounts()),
            ),
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
