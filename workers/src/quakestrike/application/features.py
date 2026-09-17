"""Application ports for building prediction input from event history."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from quakestrike.domain.features import (
    FeatureObservation,
    FeatureSnapshot,
    HistoryCoverage,
    HistoryReadiness,
    PredictionDecision,
    build_prediction_decision,
)


@dataclass(frozen=True, slots=True)
class HistorySelection:
    """Rows and explicit source coverage evidence for one feature anchor."""

    observations: tuple[FeatureObservation, ...]
    coverage: HistoryCoverage | None


class FeatureHistoryQuery(Protocol):
    """Read one row per stable event for a feature anchor."""

    def select_prior_history(
        self,
        anchor: FeatureObservation,
        *,
        coverage: HistoryCoverage | None = None,
    ) -> HistorySelection:
        """Return prior rows and independently validated coverage evidence."""


@dataclass(frozen=True, slots=True)
class PredictionSnapshotRequest:
    """Input contract for the pure prediction-snapshot decision."""

    anchor: FeatureObservation
    history: Sequence[FeatureObservation]
    coverage: HistoryCoverage | None
    input_schema_version: str


@dataclass(frozen=True, slots=True)
class PredictionSnapshotResult:
    """Decision plus the values needed to form a durable work request."""

    decision: PredictionDecision
    snapshot: FeatureSnapshot | None
    readiness: HistoryReadiness | None


def decide_prediction_snapshot(
    request: PredictionSnapshotRequest,
) -> PredictionSnapshotResult:
    """Apply the domain gates without creating a database or queue side effect."""

    decision = build_prediction_decision(
        request.anchor,
        request.history,
        request.coverage,
        input_schema_version=request.input_schema_version,
    )
    return PredictionSnapshotResult(
        decision=decision,
        snapshot=decision.snapshot,
        readiness=decision.readiness,
    )
