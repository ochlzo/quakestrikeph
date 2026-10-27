"""Application-facing transaction contracts for durable ingestion work."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from quakestrike.domain.features import HistoryCoverage


class FatalIdentityConflict(ValueError):
    """A durable source identity is already mapped to another stable event."""


class ActiveIngestionRun(ValueError):
    """Another pending, running, or retryable ingestion run owns the slot."""


class RunIdentityConflict(ValueError):
    """A requested run ID already refers to different durable work."""


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
    prediction_skip_reason: str | None = None


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
    worker_execution_id: UUID | None = None
    input_key: str | None = None
    revision: EventRevisionRequest | None = None
    prediction: PredictionWorkRequest | None = None


@dataclass(frozen=True, slots=True)
class FeatureEventTransactionRequest:
    """Revision input plus the evidence needed to decide prediction work."""

    event_id: UUID
    ingestion_run_id: UUID
    revision: EventRevisionRequest
    model_release_id: UUID
    correlation_id: UUID
    worker_execution_id: UUID | None = None
    input_key: str | None = None
    history_coverage: HistoryCoverage | None = None
    job_id: UUID | None = None
    dispatch_id: UUID | None = None
    idempotency_key: str | None = None


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
    prediction_skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RunClaim:
    """A worker's fenced right to process one logical ingestion run."""

    run_id: UUID
    worker_execution_id: UUID
    correlation_id: UUID
    attempt_count: int
    trigger_type: str


@dataclass(frozen=True, slots=True)
class RunCounters:
    """Absolute counters for one logical run's distinct inputs."""

    events_found: int
    events_inserted: int
    events_revised: int
    events_unchanged: int
    events_rejected: int


@dataclass(frozen=True, slots=True)
class IngestionRunState:
    """Read-only state needed by bootstrap resume and readiness checks."""

    run_id: UUID
    trigger_type: str
    status: str
    correlation_id: UUID
    attempt_count: int
    events_found: int
    events_inserted: int
    events_revised: int
    events_unchanged: int
    events_rejected: int
    error_code: str | None = None
    error_message: str | None = None
    snapshot_sha256: str | None = None
    enriched_snapshot_sha256: str | None = None
    finished_at: datetime | None = None
    retention_checked_at: datetime | None = None


class IngestionTransactions(Protocol):
    """Atomic persistence operations required by later ingestion phases."""

    def create_run_with_dispatch(self, request: RunDispatchRequest) -> RunDispatchResult:
        """Create one active run and dispatch, or return the existing pair."""

    def process_event(self, request: EventTransactionRequest) -> EventTransactionResult:
        """Lock or create an event and atomically add its dependent work."""

    def process_event_with_features(
        self, request: FeatureEventTransactionRequest
    ) -> EventTransactionResult:
        """Build the snapshot and persist all eligible work in one transaction."""

    def input_checkpoint_exists(self, run_id: UUID, input_key: str) -> bool:
        """Return whether one normalized input already has a durable outcome."""
