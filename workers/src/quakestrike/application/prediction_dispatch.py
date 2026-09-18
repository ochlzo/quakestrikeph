"""Compatibility names for prediction queue target types."""

from quakestrike.application.dispatch import (
    DispatchClaim,
    DispatchPublisher,
    DispatchStore,
    DurableDispatcher,
    PredictionDispatch,
)

PredictionDispatchClaim = DispatchClaim
PredictionDispatchStore = DispatchStore
PredictionPublisher = DispatchPublisher
DurablePredictionDispatcher = DurableDispatcher

__all__ = [
    "DurablePredictionDispatcher",
    "PredictionDispatch",
    "PredictionDispatchClaim",
    "PredictionDispatchStore",
    "PredictionPublisher",
]
