from datetime import UTC, datetime

import pytest

from quakestrike.domain.prediction import (
    InvalidPredictionOutput,
    compose_forecast,
)
from quakestrike.infrastructure.models.deterministic_test import DeterministicTestModel

EVENT_TIME = datetime(2026, 9, 23, 12, tzinfo=UTC)


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
