import json
import math
from dataclasses import FrozenInstanceError
from pathlib import Path
from random import Random
from uuid import uuid4

import pytest

from quakestrike.alert_testing.domain.scenarios import (
    WINDOW_MS,
    validate_inputs,
)
from quakestrike.alert_testing.domain.synthetic_observations import generate_observations
from quakestrike.domain.alerts import alert_distance_km


@pytest.fixture
def inputs():
    return json.loads(
        (Path(__file__).parents[1] / "fixtures/alert_testing/scenario.json").read_text()
    )


def test_optional_quantiles_follow_production_rules_and_values_are_frozen(inputs):
    for name in ("q05", "q50", "q95"):
        inputs[name] = ""
    assert validate_inputs(inputs).quantiles is None
    inputs.update(q05="-1", q50="0", q95="11")
    values = validate_inputs(inputs)
    assert values.quantiles == (-1, 0, 11)
    assert (values.p1, values.p4, values.p5) == (0.82, 0.28, 0.08)
    with pytest.raises(FrozenInstanceError):
        values.radius = 1


@pytest.mark.parametrize(
    "latitude,longitude,radius",
    [
        (9.86, 125.55, 42),
        (89.99, 179.99, 100),
        (-89.99, -179.99, 100),
        (90, 180, 42),
        (-90, -180, 42),
        (0, 0, 20015),
        (0, 179.99, 0.1),
    ],
)
@pytest.mark.parametrize("seed", [0])
def test_controlled_randomness_obeys_geometry_and_immediate_clock(
    inputs, latitude, longitude, radius, seed
):
    inputs.update(latitude=str(latitude), longitude=str(longitude), radius=str(radius))
    values = validate_inputs(inputs)
    now = values.event_time_ms + 3_600_000
    observations = generate_observations(values, now, Random(seed).random, str(uuid4()))
    assert len(observations) == values.local + values.background
    assert len({item.event_id for item in observations}) == len(observations)
    assert [item.event_time_ms for item in observations] == sorted(
        item.event_time_ms for item in observations
    )
    assert sum(item.kind == "inside" for item in observations) == values.local - values.spillover
    assert sum(item.kind == "spillover" for item in observations) == values.spillover
    assert sum(item.kind == "background" for item in observations) == values.background
    for item in observations:
        assert -90 <= item.latitude <= 90 and -180 <= item.longitude < 180
        assert 1 <= item.magnitude <= 5 and 5 <= item.depth_km <= 60
        assert item.location_description
        assert values.event_time_ms < item.event_time_ms <= now
        actual = alert_distance_km(latitude, longitude, item.latitude, item.longitude)
        assert math.isclose(actual, item.distance_km, rel_tol=1e-7, abs_tol=1e-6)
        assert actual < radius if item.kind == "inside" else actual > radius
    with pytest.raises(FrozenInstanceError):
        observations[0].latitude = 0


@pytest.mark.parametrize("offset", [-3_600_000, 0, 1, 2 * WINDOW_MS])
def test_edited_event_respects_exact_forecast_window(inputs, offset):
    values = validate_inputs(inputs)
    now = values.event_time_ms + offset
    observations = generate_observations(values, now, lambda: 0.999999999, str(uuid4()))
    upper = (
        min(now, values.event_time_ms + WINDOW_MS)
        if offset > 0
        else values.event_time_ms + WINDOW_MS
    )
    assert all(values.event_time_ms < point.event_time_ms <= upper for point in observations)


def test_repeated_settings_generate_fresh_positions_and_exact_spillover(inputs):
    values = validate_inputs(inputs)
    event_id = str(uuid4())
    first = generate_observations(
        values, values.event_time_ms + 3_600_000, Random(1).random, event_id
    )
    second = generate_observations(
        values, values.event_time_ms + 3_600_000, Random(2).random, event_id
    )
    assert {(point.latitude, point.longitude) for point in first} != {
        (point.latitude, point.longitude) for point in second
    }
    for sample in (0, 0.999999):
        points = generate_observations(
            values, values.event_time_ms + 3_600_000, lambda sample=sample: sample, event_id
        )
        assert sum(point.kind == "spillover" for point in points) == values.spillover
