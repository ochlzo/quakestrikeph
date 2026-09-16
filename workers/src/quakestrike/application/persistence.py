"""Application-facing transaction contracts for durable ingestion work."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RunDispatchRequest:
    run_id: UUID
    dispatch_id: UUID
    trigger_type: str
    correlation_id: UUID
    requested_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RunDispatchResult:
    run_id: UUID
    dispatch_id: UUID
    created: bool


@dataclass(frozen=True, slots=True)
class EventRevisionRequest:
    event_revision_id: UUID
    ingestion_run_id: UUID
    source_bulletin_id: str | None
    source_event_group_id: str | None
    source_url: str
    source_time_precision: str
    event_time: datetime
    latitude: Decimal
    longitude: Decimal
    depth_km: Decimal
    magnitude: Decimal
    location_description: str
    origin: str | None = None


@dataclass(frozen=True, slots=True)
class PredictionWorkRequest:
    job_id: UUID
    dispatch_id: UUID
    model_release_id: UUID
    input_snapshot_hash: str
    input_snapshot_json: Mapping[str, object]
    idempotency_key: str
    correlation_id: UUID


@dataclass(frozen=True, slots=True)
class EventTransactionRequest:
    event_id: UUID
    ingestion_run_id: UUID
    revision: EventRevisionRequest | None = None
    prediction: PredictionWorkRequest | None = None


@dataclass(frozen=True, slots=True)
class EventTransactionResult:
    event_id: UUID
    event_revision_id: UUID | None
    revision_number: int | None
    prediction_job_id: UUID | None
    dispatch_id: UUID | None
    event_created: bool
    revision_created: bool
    prediction_created: bool


class IngestionTransactions(Protocol):
    """Atomic persistence operations required by later ingestion phases."""

    def create_run_with_dispatch(self, request: RunDispatchRequest) -> RunDispatchResult:
        """Create one active run and dispatch, or return the existing pair."""

    def process_event(self, request: EventTransactionRequest) -> EventTransactionResult:
        """Lock or create an event and atomically add its dependent work."""
