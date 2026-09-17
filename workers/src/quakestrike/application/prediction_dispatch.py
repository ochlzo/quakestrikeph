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


def publish_prediction_after_commit(
    result: EventTransactionResult,
    *,
    correlation_id: UUID,
    publisher: PredictionPublisher,
) -> bool:
    """Publish only newly created work after the database transaction returns.

    A replay that observes an existing job deliberately does not publish a
    second command.  Queue failures propagate to the caller; the durable job
    and dispatch remain available for the dispatcher to retry.
    """

    if (
        not result.prediction_created
        or result.prediction_job_id is None
        or result.dispatch_id is None
    ):
        return False
    publisher.publish(
        PredictionDispatch(
            dispatch_id=result.dispatch_id,
            job_id=result.prediction_job_id,
            correlation_id=correlation_id,
        )
    )
    return True


def process_feature_event_and_publish_prediction(
    transactions: IngestionTransactions,
    request: FeatureEventTransactionRequest,
    publisher: PredictionPublisher,
) -> EventTransactionResult:
    """Persist feature work, then publish a new dispatch after commit."""

    result = transactions.process_event_with_features(request)
    publish_prediction_after_commit(
        result,
        correlation_id=request.correlation_id,
        publisher=publisher,
    )
    return result
