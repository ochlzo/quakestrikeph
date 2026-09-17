"""Application seam for publishing committed prediction work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from quakestrike.application.persistence import (
    EventTransactionResult,
    FeatureEventTransactionRequest,
    IngestionTransactions,
)


@dataclass(frozen=True, slots=True)
class PredictionDispatch:
    """The identifiers needed to deliver one already-committed job."""

    dispatch_id: UUID
    job_id: UUID
    correlation_id: UUID


class PredictionPublisher(Protocol):
    """Port implemented by the queue adapter."""

    def publish(self, dispatch: PredictionDispatch) -> None:
        """Publish one IDs-only prediction command."""


@dataclass(frozen=True, slots=True)
class PredictionDispatchClaim:
    """A database-backed claim held while a command is published."""

    dispatch: PredictionDispatch
    token: UUID


class PredictionDispatchStore(Protocol):
    """Durable lifecycle operations for one prediction dispatch row."""

    def claim(self, dispatch: PredictionDispatch) -> PredictionDispatchClaim | None:
        """Claim a ready dispatch, or return none for an unavailable row."""

    def mark_enqueued(self, claim: PredictionDispatchClaim) -> None:
        """Record broker acceptance for the current claim."""

    def mark_retry(self, claim: PredictionDispatchClaim, error: Exception) -> None:
        """Make a failed publication retryable under the current claim."""


class PredictionDispatchLifecycle(Protocol):
    """Post-commit boundary used by the ingestion application flow."""

    def dispatch(self, dispatch: PredictionDispatch) -> bool:
        """Claim, publish, and record the durable dispatch outcome."""


class DurablePredictionDispatcher:
    """Coordinate durable dispatch state around an IDs-only queue publisher."""

    def __init__(self, store: PredictionDispatchStore, publisher: PredictionPublisher) -> None:
        self._store = store
        self._publisher = publisher

    def dispatch(self, dispatch: PredictionDispatch) -> bool:
        claim = self._store.claim(dispatch)
        if claim is None:
            return False
        try:
            self._publisher.publish(claim.dispatch)
        except Exception as error:
            self._store.mark_retry(claim, error)
            raise
        self._store.mark_enqueued(claim)
        return True


def publish_prediction_after_commit(
    result: EventTransactionResult,
    *,
    correlation_id: UUID,
    dispatcher: PredictionDispatchLifecycle,
) -> bool:
    """Dispatch only newly created work after the database transaction returns.

    A replay that observes an existing job deliberately does not publish a
    second command.  The lifecycle claims and updates the durable dispatch
    around the queue publication.
    """

    if (
        not result.prediction_created
        or result.prediction_job_id is None
        or result.dispatch_id is None
    ):
        return False
    return dispatcher.dispatch(
        PredictionDispatch(
            dispatch_id=result.dispatch_id,
            job_id=result.prediction_job_id,
            correlation_id=correlation_id,
        )
    )


def process_feature_event_and_publish_prediction(
    transactions: IngestionTransactions,
    request: FeatureEventTransactionRequest,
    dispatcher: PredictionDispatchLifecycle,
) -> EventTransactionResult:
    """Persist feature work, then run its durable dispatch after commit."""

    result = transactions.process_event_with_features(request)
    publish_prediction_after_commit(
        result,
        correlation_id=request.correlation_id,
        dispatcher=dispatcher,
    )
    return result
