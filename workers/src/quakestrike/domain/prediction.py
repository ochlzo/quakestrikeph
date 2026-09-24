"""Validation and composition for the v2 forecast output."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

PREDICTION_PROCESSING_LEASE_SECONDS = 900


class InvalidPredictionOutput(ValueError):
    """A model value cannot be published as a forecast."""


@dataclass(frozen=True, slots=True)
class ForecastOutput:
    window_start: datetime
    window_end: datetime
    probability_m1_plus_24h: float
    probability_m4_plus_24h: float
    probability_m5_plus_24h: float
    expected_m1_plus_count_24h: float
    activity_radius_median_km_24h: float | None
    maximum_magnitude_q05_24h: float | None
    maximum_magnitude_q50_24h: float | None
    maximum_magnitude_q95_24h: float | None


ROUTE_NAMES = frozenset(
    {
        "m1_probability",
        "m4_given_m1",
        "m5_given_m4",
        "expected_count",
        "radius_median",
        "maximum_q05",
        "maximum_q50",
        "maximum_q95",
    }
)


def compose_forecast(raw: Mapping[str, object], event_time: datetime) -> ForecastOutput:
    """Reject bad route values before they reach the database."""

    if set(raw) != ROUTE_NAMES or event_time.tzinfo is None or event_time.utcoffset() is None:
        raise InvalidPredictionOutput("The output contract or event time is invalid.")
    values: dict[str, float | None] = {}
    for name, value in raw.items():
        if value is None and name in {"radius_median", "maximum_q05", "maximum_q50", "maximum_q95"}:
            values[name] = None
            continue
        if isinstance(value, (bool, str, bytes)):
            raise InvalidPredictionOutput(f"{name} must be finite and numeric.")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise InvalidPredictionOutput(f"{name} must be finite and numeric.") from error
        if not math.isfinite(number):
            raise InvalidPredictionOutput(f"{name} must be finite and numeric.")
        values[name] = number

    m1 = values["m1_probability"]
    m4_given_m1 = values["m4_given_m1"]
    m5_given_m4 = values["m5_given_m4"]
    assert m1 is not None and m4_given_m1 is not None and m5_given_m4 is not None
    if any(not 0 <= probability <= 1 for probability in (m1, m4_given_m1, m5_given_m4)):
        raise InvalidPredictionOutput("A probability is outside [0, 1].")
    m4 = m1 * m4_given_m1
    m5 = m4 * m5_given_m4
    count = values["expected_count"]
    radius = values["radius_median"]
    if count is None or count < 0 or (radius is not None and radius < 0):
        raise InvalidPredictionOutput("A count or radius is negative.")
    quantiles = (values["maximum_q05"], values["maximum_q50"], values["maximum_q95"])
    if not (
        all(value is None for value in quantiles) or all(value is not None for value in quantiles)
    ):
        raise InvalidPredictionOutput("Magnitude quantiles must be all present or all absent.")
    if quantiles[0] is not None and not (quantiles[0] <= quantiles[1] <= quantiles[2]):
        raise InvalidPredictionOutput("Magnitude quantiles are unordered.")
    return ForecastOutput(
        window_start=event_time,
        window_end=event_time + timedelta(hours=24),
        probability_m1_plus_24h=m1,
        probability_m4_plus_24h=m4,
        probability_m5_plus_24h=m5,
        expected_m1_plus_count_24h=count,
        activity_radius_median_km_24h=radius,
        maximum_magnitude_q05_24h=quantiles[0],
        maximum_magnitude_q50_24h=quantiles[1],
        maximum_magnitude_q95_24h=quantiles[2],
    )
