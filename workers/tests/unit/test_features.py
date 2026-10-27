from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quakestrike.domain.features import (
    EARTH_RADIUS_KM,
    FEATURE_NAMES,
    INPUT_SCHEMA_VERSION,
    FeatureObservation,
    HistoryCoverage,
    PredictionSkipReason,
    build_features,
    canonical_snapshot_bytes,
    create_feature_snapshot,
    evaluate_history_readiness,
    feature_snapshot_hash,
    haversine_distance_km,
)

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def _observation(
    label: str,
    event_time: datetime,
    *,
    magnitude: str = "2.0",
    latitude: str = "14.000000",
    longitude: str = "121.000000",
    precision: str = "second",
) -> FeatureObservation:
    return FeatureObservation(
        event_id=label,
        event_time=event_time,
        time_precision=precision,
        latitude=Decimal(latitude),
        longitude=Decimal(longitude),
        depth_km=Decimal("10.000"),
        magnitude=Decimal(magnitude),
    )


def test_feature_builder_uses_exact_windows_and_excludes_future_anchor_and_uncertain_minute() -> (
    None
):
    anchor = _observation("anchor", NOW, latitude="14.0", longitude="121.0")
    history = [
        _observation("lower-7d", NOW - timedelta(days=7)),
        _observation("outside", NOW - timedelta(days=7, seconds=1)),
        _observation("lower-24h", NOW - timedelta(days=1)),
        _observation("lower-1h", NOW - timedelta(hours=1)),
        _observation("minute-uncertain", NOW.replace(second=0), precision="minute"),
        _observation("below-m1", NOW - timedelta(minutes=2), magnitude="0.99"),
        _observation("future", NOW + timedelta(seconds=1), magnitude="8.0"),
        anchor,
    ]

    values = build_features(anchor, history[:-1])

    assert set(values) == set(FEATURE_NAMES)
    assert values["catalog_m1_plus_count_past_1h"] == 1
    assert values["catalog_m1_plus_count_past_24h"] == 2
    assert values["catalog_m1_plus_count_past_7d"] == 3
    assert values["local_m1_plus_count_past_24h_within_50km"] == 2
    assert values["local_m1_plus_count_past_24h_within_100km"] == 2


def test_second_precision_events_in_the_same_minute_are_ordered_but_minute_precision_is_not() -> (
    None
):
    anchor = _observation("anchor", NOW.replace(second=30), precision="second")
    second_before = _observation("second-before", NOW.replace(second=10), precision="second")
    minute_before = _observation("minute-before", NOW.replace(second=0), precision="minute")

    values = build_features(anchor, [second_before, minute_before])

    assert values["catalog_m1_plus_count_past_1h"] == 1


def test_local_distance_uses_project_radius_and_inclusive_boundary() -> None:
    anchor = _observation("anchor", NOW, latitude="0", longitude="0")
    # On the equator one degree of longitude is approximately 111.195 km.
    at_100_km = _observation(
        "at-100", NOW - timedelta(seconds=1), latitude="0", longitude="0.899320"
    )
    just_over_100_km = _observation(
        "over-100", NOW - timedelta(seconds=2), latitude="0", longitude="0.899330"
    )

    assert haversine_distance_km(anchor, at_100_km) <= 100
    assert haversine_distance_km(anchor, just_over_100_km) > 100
    values = build_features(anchor, [at_100_km, just_over_100_km])
    assert values["local_m1_plus_count_past_24h_within_100km"] == 1
    assert EARTH_RADIUS_KM == 6371.0088


def test_readiness_requires_explicit_complete_coverage_not_an_oldest_row() -> None:
    anchor = NOW
    incomplete = HistoryCoverage(
        start=anchor - timedelta(days=30),
        end=anchor,
        complete=False,
    )

    result = evaluate_history_readiness(anchor, incomplete)

    assert result.ready is False
    assert result.reason == PredictionSkipReason.INCOMPLETE_FEATURE_HISTORY.value
    assert evaluate_history_readiness(anchor, None).reason == (
        PredictionSkipReason.HISTORY_COVERAGE_UNAVAILABLE.value
    )


def test_snapshot_is_exactly_ten_fields_and_hash_binds_schema_and_key_order() -> None:
    anchor = _observation("anchor", NOW, magnitude="4.20", latitude="14.123456")
    features = build_features(anchor, [])
    reordered = {name: features[name] for name in reversed(FEATURE_NAMES)}

    first = create_feature_snapshot(features)
    second = create_feature_snapshot(reordered)

    assert dict(first.values) == dict(second.values)
    assert first.canonical_bytes == second.canonical_bytes
    assert first.sha256 == second.sha256 == feature_snapshot_hash(features)
    assert set(json_key_names(first.values)) == set(FEATURE_NAMES)
    assert first.sha256 != feature_snapshot_hash(features, "quakestrike.prediction-input.v2")
    assert b'"input_schema_version":"quakestrike.prediction-input.v1"' in canonical_snapshot_bytes(
        features, INPUT_SCHEMA_VERSION
    )


def test_snapshot_rejects_missing_unknown_and_nonfinite_values() -> None:
    anchor = _observation("anchor", NOW)
    features = build_features(anchor, [])

    with pytest.raises(ValueError, match="exactly"):
        create_feature_snapshot(
            {name: value for name, value in features.items() if name != FEATURE_NAMES[0]}
        )
    with pytest.raises(ValueError, match="exactly"):
        create_feature_snapshot({**features, "unexpected": 1})
    with pytest.raises(ValueError, match="finite"):
        create_feature_snapshot({**features, "anchor_magnitude": float("nan")})


def json_key_names(values: object) -> list[str]:
    assert isinstance(values, Mapping)
    return list(values)
