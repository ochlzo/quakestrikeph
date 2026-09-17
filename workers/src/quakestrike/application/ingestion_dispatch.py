"""Application orchestration for durable ingestion dispatches."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

DispatchState = Literal["retry_wait", "stopped"]
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class IngestionDispatch:
    """The stable identifiers needed to publish one ingestion command."""

    dispatch_id: UUID
    run_id: UUID
    correlation_id: UUID


@dataclass(frozen=True, slots=True)
class IngestionDispatchClaim:
    """A fenced, time-limited right to publish one dispatch."""

    dispatch: IngestionDispatch
    token: UUID


@dataclass(frozen=True, slots=True)
class DispatchBatchResult:
    """Durable outcomes from one bounded dispatcher scan."""

    claimed: int
    enqueued: int
    retry_wait: int
    stopped: int


class DispatchClaimLost(RuntimeError):
    """Raised when a dispatcher no longer owns the durable dispatch claim."""


class IngestionDispatchStore(Protocol):
    """Persistence boundary for claim, publish, and acceptance transitions."""

    def claim_due(self, limit: int, *, now: datetime) -> tuple[IngestionDispatchClaim, ...]:
        """Claim only due ingestion dispatches and commit each claim before returning."""

    def mark_enqueued(self, claim: IngestionDispatchClaim) -> None:
        """Record queue acceptance while fencing with the claim token."""

    def mark_retry(
        self,
        claim: IngestionDispatchClaim,
        error: Exception,
        *,
        now: datetime,
    ) -> DispatchState:
        """Schedule a bounded retry or move exhausted work to stopped."""


class IngestionPublisher(Protocol):
    """External publication boundary for identifier-only ingestion commands."""

    def publish(self, dispatch: IngestionDispatch) -> None:
        """Publish a claimed dispatch to the ingestion queue."""


class DurableIngestionDispatcher:
    """Publish committed claims and persist the result of each attempt."""

    def __init__(
        self,
        store: IngestionDispatchStore,
        publisher: IngestionPublisher,
        *,
        batch_size: int,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        if not 1 <= batch_size <= 10:
            raise ValueError("Dispatcher batch size must be between 1 and 10.")
        self._store = store
        self._publisher = publisher
        self._batch_size = batch_size
        self._clock = clock

    def dispatch_due(self) -> DispatchBatchResult:
        now = self._clock()
        claims = self._store.claim_due(self._batch_size, now=now)
        enqueued = 0
        retry_wait = 0
        stopped = 0

        for claim in claims:
            try:
                self._publisher.publish(claim.dispatch)
            except Exception as error:
                state = self._store.mark_retry(claim, error, now=self._clock())
                if state == "retry_wait":
                    retry_wait += 1
                elif state == "stopped":
                    stopped += 1
                else:
                    raise ValueError(f"Unknown dispatch retry state: {state}") from error
            else:
                self._store.mark_enqueued(claim)
                enqueued += 1

        return DispatchBatchResult(
            claimed=len(claims),
            enqueued=enqueued,
            retry_wait=retry_wait,
            stopped=stopped,
        )
