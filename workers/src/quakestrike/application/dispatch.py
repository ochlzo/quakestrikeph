"""Shared application seam for durable queue submission."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

DispatchTargetKind = Literal["ingestion", "prediction"]
DispatchState = Literal["retry_wait", "stopped"]
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class IngestionDispatch:
    """The stable identifiers needed to publish one ingestion command."""

    dispatch_id: UUID
    run_id: UUID
    correlation_id: UUID

    @property
    def target_kind(self) -> Literal["ingestion"]:
        return "ingestion"


@dataclass(frozen=True, slots=True)
class PredictionDispatch:
    """The stable identifiers needed to publish one prediction command."""

    dispatch_id: UUID
    job_id: UUID
    correlation_id: UUID

    @property
    def target_kind(self) -> Literal["prediction"]:
        return "prediction"


type DispatchTarget = IngestionDispatch | PredictionDispatch


@dataclass(frozen=True, slots=True)
class DispatchClaim:
    """A fenced, time-limited right to publish one durable dispatch."""

    dispatch: DispatchTarget
    token: UUID


class DispatchClaimLost(RuntimeError):
    """Raised when a dispatcher no longer owns the durable dispatch claim."""


class DispatchPermanentError(ValueError):
    """Raised when a queue command cannot become valid through retrying."""


class DispatchStore(Protocol):
    """Persistence boundary for the shared dispatch state machine."""

    def claim_due(self, limit: int, *, now: datetime) -> tuple[DispatchClaim, ...]:
        """Claim due rows and commit each claim before publication."""

    def mark_enqueued(self, claim: DispatchClaim) -> None:
        """Record queue acceptance while fencing with the claim token."""

    def mark_retry(
        self,
        claim: DispatchClaim,
        error: Exception,
        *,
        now: datetime,
    ) -> DispatchState:
        """Schedule a bounded retry or stop exhausted work."""

    def mark_stopped(self, claim: DispatchClaim, error: Exception, *, now: datetime) -> None:
        """Stop a claim whose durable command is permanently invalid."""


class DispatchPublisher(Protocol):
    """Queue adapter for one target kind."""

    def publish(self, dispatch: DispatchTarget) -> None:
        """Publish one IDs-only command."""


@dataclass(frozen=True, slots=True)
class DispatchTargetCounts:
    claimed: int = 0
    enqueued: int = 0
    retry_wait: int = 0
    stopped: int = 0


@dataclass(frozen=True, slots=True)
class DispatchBatchResult:
    """Durable outcomes from one bounded Dispatcher scan."""

    claimed: int
    enqueued: int
    retry_wait: int
    stopped: int
    target_counts: tuple[tuple[DispatchTargetKind, DispatchTargetCounts], ...] = field(
        default=(),
        compare=False,
        repr=False,
    )

    def target_counts_for(self, target_kind: DispatchTargetKind) -> DispatchTargetCounts:
        for kind, counts in self.target_counts:
            if kind == target_kind:
                return counts
        return DispatchTargetCounts()


class DurableDispatcher:
    """Publish committed ingestion and prediction claims through one state machine."""

    def __init__(
        self,
        store: DispatchStore,
        publishers: Mapping[DispatchTargetKind, DispatchPublisher] | DispatchPublisher,
        *,
        batch_size: int,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        if not 1 <= batch_size <= 10:
            raise ValueError("Dispatcher batch size must be between 1 and 10.")
        if isinstance(publishers, Mapping):
            configured_publishers = dict(publishers)
            missing = {"ingestion", "prediction"} - configured_publishers.keys()
            if missing:
                missing_kinds = ", ".join(sorted(missing))
                raise ValueError(f"Dispatcher publishers missing: {missing_kinds}.")
        else:
            configured_publishers = {"ingestion": publishers}
        self._store = store
        self._publishers = configured_publishers
        self._batch_size = batch_size
        self._clock = clock

    def dispatch_due(self) -> DispatchBatchResult:
        now = self._clock()
        claims = self._store.claim_due(self._batch_size, now=now)
        totals = [0, 0, 0, 0]
        target_totals: dict[DispatchTargetKind, list[int]] = {
            "ingestion": [0, 0, 0, 0],
            "prediction": [0, 0, 0, 0],
        }

        for claim in claims:
            target_kind = claim.dispatch.target_kind
            totals[0] += 1
            target_totals[target_kind][0] += 1
            publisher = self._publishers[target_kind]
            try:
                publisher.publish(claim.dispatch)
            except (DispatchPermanentError, TypeError, ValueError) as error:
                self._store.mark_stopped(claim, error, now=self._clock())
                totals[3] += 1
                target_totals[target_kind][3] += 1
            except Exception as error:
                state = self._store.mark_retry(claim, error, now=self._clock())
                if state == "retry_wait":
                    totals[2] += 1
                    target_totals[target_kind][2] += 1
                elif state == "stopped":
                    totals[3] += 1
                    target_totals[target_kind][3] += 1
                else:
                    raise ValueError(f"Unknown dispatch retry state: {state}") from error
            else:
                self._store.mark_enqueued(claim)
                totals[1] += 1
                target_totals[target_kind][1] += 1

        target_counts = tuple(
            (
                target_kind,
                DispatchTargetCounts(*target_totals[target_kind]),
            )
            for target_kind in ("ingestion", "prediction")
        )
        return DispatchBatchResult(*totals, target_counts=target_counts)
