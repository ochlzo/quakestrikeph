from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from quakestrike.application.persistence import RunDispatchRequest, RunDispatchResult
from quakestrike.application.scheduling import ScheduleIngestionPoll

NOW = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)


@dataclass
class RecordingRunStore:
    result: RunDispatchResult
    requests: list[RunDispatchRequest]

    def create_run_with_dispatch(self, request: RunDispatchRequest) -> RunDispatchResult:
        self.requests.append(request)
        return self.result


def test_scheduled_poll_submits_one_atomic_run_dispatch_request() -> None:
    existing_run_id = UUID("00000000-0000-0000-0000-000000000101")
    existing_dispatch_id = UUID("00000000-0000-0000-0000-000000000102")
    store = RecordingRunStore(
        result=RunDispatchResult(
            run_id=existing_run_id,
            dispatch_id=existing_dispatch_id,
            created=False,
        ),
        requests=[],
    )
    generated_ids = iter(
        UUID(f"00000000-0000-0000-0000-00000000010{value}") for value in range(3, 6)
    )

    result = ScheduleIngestionPoll(
        store,
        clock=lambda: NOW,
        id_factory=lambda: next(generated_ids),
    ).execute()

    assert result == store.result
    assert store.requests == [
        RunDispatchRequest(
            run_id=UUID("00000000-0000-0000-0000-000000000103"),
            dispatch_id=UUID("00000000-0000-0000-0000-000000000104"),
            trigger_type="scheduled",
            correlation_id=UUID("00000000-0000-0000-0000-000000000105"),
            requested_at=NOW,
        )
    ]
