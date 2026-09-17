from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from quakestrike.application.features import PredictionSnapshotRequest, decide_prediction_snapshot
from quakestrike.domain.features import FeatureObservation, HistoryCoverage


def test_application_snapshot_seam_returns_a_complete_snapshot_for_an_eligible_anchor() -> None:
    anchor_time = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    anchor = FeatureObservation(
        event_id=uuid4(),
        event_time=anchor_time,
        time_precision="second",
        latitude=Decimal("14"),
        longitude=Decimal("121"),
        depth_km=Decimal("10"),
        magnitude=Decimal("1.0"),
    )
    request = PredictionSnapshotRequest(
        anchor=anchor,
        history=(),
        coverage=HistoryCoverage(anchor_time - timedelta(days=7), anchor_time, True),
        input_schema_version="quakestrike.prediction-input.v1",
    )

    result = decide_prediction_snapshot(request)

    assert result.snapshot is not None
    assert result.snapshot.values["anchor_magnitude"] == 1
    assert result.readiness is not None and result.readiness.ready is True
