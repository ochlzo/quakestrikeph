"""Application use case for one scheduled ingestion polling tick."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from quakestrike.application.persistence import RunDispatchRequest, RunDispatchResult

Clock = Callable[[], datetime]
IdFactory = Callable[[], UUID]


class ScheduledRunStore(Protocol):
    """Persistence boundary owned by the scheduler use case."""

    def create_run_with_dispatch(self, request: RunDispatchRequest) -> RunDispatchResult:
        """Create one active scheduled run and dispatch, or return the active pair."""


class ScheduleIngestionPoll:
    """Build the IDs for a tick and delegate overlap handling to PostgreSQL."""

    def __init__(
        self,
        store: ScheduledRunStore,
        *,
        clock: Clock = lambda: datetime.now(UTC),
        id_factory: IdFactory = uuid4,
    ) -> None:
        self._store = store
        self._clock = clock
        self._id_factory = id_factory

    def execute(self) -> RunDispatchResult:
        requested_at = self._clock()
        return self._store.create_run_with_dispatch(
            RunDispatchRequest(
                run_id=self._id_factory(),
                dispatch_id=self._id_factory(),
                trigger_type="scheduled",
                correlation_id=self._id_factory(),
                requested_at=requested_at,
            )
        )
