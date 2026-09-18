"""Compatibility names for the shared durable dispatch seam."""

from quakestrike.application.dispatch import (
    DispatchBatchResult,
    DispatchClaim,
    DispatchClaimLost,
    DispatchPublisher,
    DispatchState,
    DispatchStore,
    DurableDispatcher,
    IngestionDispatch,
)

IngestionDispatchClaim = DispatchClaim
IngestionDispatchStore = DispatchStore
IngestionPublisher = DispatchPublisher
DurableIngestionDispatcher = DurableDispatcher

__all__ = [
    "DispatchBatchResult",
    "DispatchClaimLost",
    "DispatchState",
    "DurableIngestionDispatcher",
    "IngestionDispatch",
    "IngestionDispatchClaim",
    "IngestionDispatchStore",
    "IngestionPublisher",
]
