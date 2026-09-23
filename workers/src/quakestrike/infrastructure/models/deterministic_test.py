"""Deterministic prediction adapter for issue #16 integration testing."""

from __future__ import annotations

from collections.abc import Mapping


class DeterministicTestModel:
    """Return stable route values until the verified SEIS runner arrives in issue #17."""

    def predict(self, features: Mapping[str, object]) -> Mapping[str, object]:
        magnitude = float(features["anchor_magnitude"])
        return {
            "m1_probability": 0.6,
            "m4_given_m1": 0.4,
            "m5_given_m4": 0.25,
            "expected_count": 1.0,
            "radius_median": 50.0,
            "maximum_q05": max(1.0, magnitude - 0.5),
            "maximum_q50": max(1.0, magnitude),
            "maximum_q95": max(1.0, magnitude + 0.5),
        }
