from datetime import UTC, datetime, timedelta

import pytest

from quakestrike.domain.prediction import (
    InvalidPredictionOutput,
    compose_forecast,
)
from quakestrike.infrastructure.models.deterministic_test import DeterministicTestModel

EVENT_TIME = datetime(2026, 9, 23, 12, tzinfo=UTC)


def test_composition_and_exact_window() -> None:
    raw = DeterministicTestModel().predict({"anchor_magnitude": 4.2})
    forecast = compose_forecast(raw, EVENT_TIME)
    assert forecast.window_start == EVENT_TIME
    assert forecast.window_end == EVENT_TIME + timedelta(hours=24)
    assert forecast.probability_m1_plus_24h == 0.6
    assert forecast.probability_m4_plus_24h == pytest.approx(0.24)
    assert forecast.probability_m5_plus_24h == pytest.approx(0.06)
    assert (
        forecast.maximum_magnitude_q05_24h,
        forecast.maximum_magnitude_q50_24h,
        forecast.maximum_magnitude_q95_24h,
    ) == (3.7, 4.2, 4.7)


@pytest.mark.parametrize(
    "change",
    [
        {"m1_probability": 1.01},
        {"m4_given_m1": -0.01},
        {"m4_given_m1": "0.4"},
        {"expected_count": -1},
        {"radius_median": float("inf")},
        {"maximum_q05": 8},
        {"maximum_q50": None},
    ],
)
def test_invalid_route_values_are_rejected(change) -> None:
    raw = DeterministicTestModel().predict({"anchor_magnitude": 4.2}) | change
    with pytest.raises(InvalidPredictionOutput):
        compose_forecast(raw, EVENT_TIME)
