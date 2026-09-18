"""The observation-only feature contract used by live prediction work.

This module deliberately knows nothing about PostgreSQL, SQLAlchemy, Celery, or
model implementations.  The database adapter turns one latest revision per
event into :class:`FeatureObservation` values, and this module applies the
same rules to those values in every caller.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType
from typing import Final

INPUT_SCHEMA_VERSION: Final[str] = "quakestrike.prediction-input.v1"
MINIMUM_PREDICTION_MAGNITUDE: Final[Decimal] = Decimal("1.0")
HISTORY_WINDOW: Final[timedelta] = timedelta(days=7)
EARTH_RADIUS_KM: Final[float] = 6371.0088
LOCAL_RADII_KM: Final[tuple[int, int]] = (50, 100)

FEATURE_NAMES: Final[tuple[str, ...]] = (
    "anchor_magnitude",
    "anchor_depth_km",
    "anchor_latitude",
    "anchor_longitude",
    "anchor_time_is_minute_precision",
    "catalog_m1_plus_count_past_1h",
    "catalog_m1_plus_count_past_24h",
    "catalog_m1_plus_count_past_7d",
    "local_m1_plus_count_past_24h_within_50km",
    "local_m1_plus_count_past_24h_within_100km",
)

_GLOBAL_WINDOWS: Final[tuple[tuple[str, timedelta], ...]] = (
    ("1h", timedelta(hours=1)),
    ("24h", timedelta(days=1)),
    ("7d", HISTORY_WINDOW),
)


class PredictionSkipReason(StrEnum):
    """Stable reasons why a valid revision did not create prediction work."""

    BELOW_M1 = "magnitude_below_m1"
    HISTORY_COVERAGE_UNAVAILABLE = "history_coverage_unavailable"
    INCOMPLETE_FEATURE_HISTORY = "incomplete_feature_history"
    HISTORY_STARTS_AFTER_REQUIRED_WINDOW = "history_starts_after_required_window"
    HISTORY_ENDS_BEFORE_ANCHOR = "history_ends_before_anchor"
    MODEL_RELEASE_UNAVAILABLE = "model_release_unavailable"


_HISTORY_SKIP_REASONS: Final[frozenset[str]] = frozenset(
    {
        PredictionSkipReason.HISTORY_COVERAGE_UNAVAILABLE.value,
        PredictionSkipReason.INCOMPLETE_FEATURE_HISTORY.value,
        PredictionSkipReason.HISTORY_STARTS_AFTER_REQUIRED_WINDOW.value,
        PredictionSkipReason.HISTORY_ENDS_BEFORE_ANCHOR.value,
    }
)


@dataclass(frozen=True, slots=True)
class FeatureObservation:
    """A validated observation used by the feature builder.

    ``event_id`` is the stable QuakeStrike event identity.  A history query
    must return at most one row for each stable event, normally its latest
    revision.  The anchor event is excluded by that identity as well as by
    the time rule, so an earlier revision cannot leak into its own features.
    """

    event_id: object
    event_time: datetime
    time_precision: str
    latitude: Decimal | int | float | str
    longitude: Decimal | int | float | str
    depth_km: Decimal | int | float | str
    magnitude: Decimal | int | float | str

    def __post_init__(self) -> None:
        _require_aware_datetime(self.event_time, "event_time")
        if self.time_precision not in {"minute", "second"}:
            raise ValueError("time_precision must be 'minute' or 'second'")
        for name in ("latitude", "longitude", "depth_km", "magnitude"):
            _as_decimal(getattr(self, name), name)

    @property
    def source_time_precision(self) -> str:
        """Compatibility name used by the persistence schema."""

        return self.time_precision


# These aliases make the public seam easy to discover without duplicating the
# domain type in the application layer.
EventObservation = FeatureObservation
EarthquakeObservation = FeatureObservation


@dataclass(frozen=True, slots=True)
class HistoryCoverage:
    """Explicit evidence that a source catalog covers an anchor's lookback.

    ``start`` is inclusive and ``end`` is exclusive.  ``complete`` must come
    from source/bootstrap validation.  The feature code never infers complete
    coverage from the timestamp of the earliest row in PostgreSQL.
    """

    start: datetime | None
    end: datetime | None
    complete: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.start is not None:
            _require_aware_datetime(self.start, "coverage start")
        if self.end is not None:
            _require_aware_datetime(self.end, "coverage end")
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("coverage end must not precede coverage start")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("coverage reason must not be blank")

    @property
    def covered_from(self) -> datetime | None:
        return self.start

    @property
    def covered_until(self) -> datetime | None:
        return self.end


HistoryCoverageEvidence = HistoryCoverage


@dataclass(frozen=True, slots=True)
class HistoryReadiness:
    """Decision for the seven-day source-coverage prerequisite."""

    ready: bool
    required_start: datetime
    required_end: datetime
    reason: str | None = None

    @property
    def skip_reason(self) -> str | None:
        return self.reason


def evaluate_history_readiness(
    anchor_time: datetime,
    coverage: HistoryCoverage | None,
) -> HistoryReadiness:
    """Check explicit coverage evidence for ``[anchor - 7d, anchor)``.

    A row that happens to be older than seven days is not proof that the source
    contained every required interval.  Callers must provide evidence whose
    ``complete`` flag was established by the source/bootstrap workflow.
    """

    _require_aware_datetime(anchor_time, "anchor_time")
    required_start = anchor_time - HISTORY_WINDOW
    if coverage is None:
        return HistoryReadiness(
            ready=False,
            required_start=required_start,
            required_end=anchor_time,
            reason=PredictionSkipReason.HISTORY_COVERAGE_UNAVAILABLE.value,
        )
    if not coverage.complete:
        return HistoryReadiness(
            ready=False,
            required_start=required_start,
            required_end=anchor_time,
            reason=_approved_history_skip_reason(coverage.reason),
        )
    if coverage.start is None:
        return HistoryReadiness(
            ready=False,
            required_start=required_start,
            required_end=anchor_time,
            reason=PredictionSkipReason.HISTORY_COVERAGE_UNAVAILABLE.value,
        )
    if coverage.start > required_start:
        return HistoryReadiness(
            ready=False,
            required_start=required_start,
            required_end=anchor_time,
            reason=PredictionSkipReason.HISTORY_STARTS_AFTER_REQUIRED_WINDOW.value,
        )
    if coverage.end is None:
        return HistoryReadiness(
            ready=False,
            required_start=required_start,
            required_end=anchor_time,
            reason=PredictionSkipReason.HISTORY_COVERAGE_UNAVAILABLE.value,
        )
    if coverage.end < anchor_time:
        return HistoryReadiness(
            ready=False,
            required_start=required_start,
            required_end=anchor_time,
            reason=PredictionSkipReason.HISTORY_ENDS_BEFORE_ANCHOR.value,
        )
    return HistoryReadiness(
        ready=True,
        required_start=required_start,
        required_end=anchor_time,
    )


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    """Immutable normalized features and their schema-bound digest."""

    values: Mapping[str, object]
    input_schema_version: str
    canonical_bytes: bytes
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    @property
    def input_snapshot_json(self) -> Mapping[str, object]:
        return self.values

    @property
    def input_snapshot_hash(self) -> str:
        return self.sha256


@dataclass(frozen=True, slots=True)
class PredictionDecision:
    """The result of applying the magnitude and history gates."""

    snapshot: FeatureSnapshot | None
    readiness: HistoryReadiness | None
    skip_reason: str | None

    @property
    def eligible(self) -> bool:
        return self.snapshot is not None and self.skip_reason is None


def strictly_before(observation: FeatureObservation, anchor: FeatureObservation) -> bool:
    """Return whether an observation is known to precede the anchor.

    When either timestamp is only precise to a minute, two observations in the
    same UTC minute have uncertain order and are excluded.  Two second-
    precision observations in that minute can be ordered normally.
    """

    return _strictly_before_time(
        observation,
        anchor.event_time,
        anchor_time_precision=anchor.time_precision,
    )


def select_usable_history(
    anchor_time: datetime,
    history: Sequence[FeatureObservation],
    *,
    anchor_time_precision: str = "minute",
    excluded_event_id: object | None = None,
) -> tuple[FeatureObservation, ...]:
    """Apply the shared history rules without constructing anchor features.

    This is the readiness seam for a declared prediction boundary.  The
    boundary has no event identity, so callers may omit ``excluded_event_id``.
    """

    _require_aware_datetime(anchor_time, "anchor_time")
    if anchor_time_precision not in {"minute", "second"}:
        raise ValueError("anchor_time_precision must be 'minute' or 'second'")
    if len({row.event_id for row in history}) != len(history):
        raise ValueError("history must contain at most one observation per event")

    lower_bound = anchor_time - HISTORY_WINDOW
    return tuple(
        row
        for row in history
        if row.event_id != excluded_event_id
        and _as_decimal(row.magnitude, "magnitude") >= MINIMUM_PREDICTION_MAGNITUDE
        and lower_bound <= row.event_time
        and _strictly_before_time(
            row,
            anchor_time,
            anchor_time_precision=anchor_time_precision,
        )
    )


def haversine_distance_km(first: FeatureObservation, second: FeatureObservation) -> float:
    """Calculate great-circle distance using the project Earth radius."""

    latitude_first = math.radians(float(first.latitude))
    latitude_second = math.radians(float(second.latitude))
    latitude_delta = latitude_second - latitude_first
    longitude_delta = math.radians(float(second.longitude) - float(first.longitude))
    haversine = math.sin(latitude_delta / 2) ** 2
    haversine += (
        math.cos(latitude_first) * math.cos(latitude_second) * math.sin(longitude_delta / 2) ** 2
    )
    haversine = min(1.0, max(0.0, haversine))
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(haversine))


def build_features(
    anchor: FeatureObservation,
    history: Sequence[FeatureObservation],
) -> dict[str, object]:
    """Build the ten observation-only features for one anchor."""

    eligible_history = select_usable_history(
        anchor.event_time,
        history,
        anchor_time_precision=anchor.time_precision,
        excluded_event_id=anchor.event_id,
    )
    values: dict[str, object] = {
        "anchor_magnitude": _json_number(anchor.magnitude, "anchor_magnitude"),
        "anchor_depth_km": _json_number(anchor.depth_km, "anchor_depth_km"),
        "anchor_latitude": _json_number(anchor.latitude, "anchor_latitude"),
        "anchor_longitude": _json_number(anchor.longitude, "anchor_longitude"),
        "anchor_time_is_minute_precision": int(anchor.time_precision == "minute"),
    }

    for name, window in _GLOBAL_WINDOWS:
        lower = anchor.event_time - window
        values[f"catalog_m1_plus_count_past_{name}"] = sum(
            lower <= row.event_time < anchor.event_time for row in eligible_history
        )

    local_history = [
        row
        for row in eligible_history
        if anchor.event_time - timedelta(days=1) <= row.event_time < anchor.event_time
    ]
    local_counts = {radius: 0 for radius in LOCAL_RADII_KM}
    for row in local_history:
        distance = haversine_distance_km(anchor, row)
        for radius in LOCAL_RADII_KM:
            if distance <= radius:
                local_counts[radius] += 1
    for radius, count in local_counts.items():
        values[f"local_m1_plus_count_past_24h_within_{radius}km"] = count
    return _normalize_feature_values(values)


def build_prediction_decision(
    anchor: FeatureObservation,
    history: Sequence[FeatureObservation],
    coverage: HistoryCoverage | None,
    *,
    input_schema_version: str = INPUT_SCHEMA_VERSION,
) -> PredictionDecision:
    """Apply the prediction gates and produce a complete snapshot when ready."""

    if _as_decimal(anchor.magnitude, "anchor magnitude") < MINIMUM_PREDICTION_MAGNITUDE:
        return PredictionDecision(
            snapshot=None,
            readiness=None,
            skip_reason=PredictionSkipReason.BELOW_M1.value,
        )
    readiness = evaluate_history_readiness(anchor.event_time, coverage)
    if not readiness.ready:
        return PredictionDecision(
            snapshot=None,
            readiness=readiness,
            skip_reason=readiness.reason,
        )
    snapshot = create_feature_snapshot(
        build_features(anchor, history),
        input_schema_version=input_schema_version,
    )
    return PredictionDecision(snapshot=snapshot, readiness=readiness, skip_reason=None)


def create_feature_snapshot(
    features: Mapping[str, object],
    *,
    input_schema_version: str = INPUT_SCHEMA_VERSION,
) -> FeatureSnapshot:
    """Normalize the exact ten fields and hash them with schema identity."""

    normalized = _normalize_feature_values(features)
    if not isinstance(input_schema_version, str) or not input_schema_version.strip():
        raise ValueError("input_schema_version must be a nonblank string")
    if input_schema_version != input_schema_version.strip():
        raise ValueError("input_schema_version must be trimmed")
    canonical_bytes = canonical_snapshot_bytes(normalized, input_schema_version)
    return FeatureSnapshot(
        values=normalized,
        input_schema_version=input_schema_version,
        canonical_bytes=canonical_bytes,
        sha256=hashlib.sha256(canonical_bytes).hexdigest(),
    )


def canonical_snapshot_bytes(
    features: Mapping[str, object],
    input_schema_version: str = INPUT_SCHEMA_VERSION,
) -> bytes:
    """Return canonical hash bytes with the input schema bound to the values.

    The stored JSON object contains exactly the ten feature names.  The hash
    envelope adds the schema identity so the same numbers under a new input
    contract cannot accidentally reuse an old prediction job.
    """

    normalized = _normalize_feature_values(features)
    if not isinstance(input_schema_version, str) or not input_schema_version.strip():
        raise ValueError("input_schema_version must be a nonblank string")
    if input_schema_version != input_schema_version.strip():
        raise ValueError("input_schema_version must be trimmed")
    envelope = {
        "features": normalized,
        "input_schema_version": input_schema_version,
    }
    return json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def feature_snapshot_hash(
    features: Mapping[str, object],
    input_schema_version: str = INPUT_SCHEMA_VERSION,
) -> str:
    """Return the lowercase SHA-256 of :func:`canonical_snapshot_bytes`."""

    return hashlib.sha256(canonical_snapshot_bytes(features, input_schema_version)).hexdigest()


snapshot_hash = feature_snapshot_hash


def _normalize_feature_values(features: Mapping[str, object]) -> dict[str, object]:
    if set(features) != set(FEATURE_NAMES):
        missing = sorted(set(FEATURE_NAMES) - set(features))
        unknown = sorted(set(features) - set(FEATURE_NAMES))
        details = []
        if missing:
            details.append(f"missing {missing}")
        if unknown:
            details.append(f"unknown {unknown}")
        detail_text = "; ".join(details)
        raise ValueError(
            f"feature snapshot must contain exactly the ten approved fields ({detail_text})"
        )

    normalized: dict[str, object] = {}
    for name in FEATURE_NAMES:
        value = features[name]
        if name == "anchor_time_is_minute_precision":
            if isinstance(value, bool) or value not in {0, 1}:
                raise ValueError(f"{name} must be 0 or 1")
            normalized[name] = int(value)
        elif name.startswith("catalog_") or name.startswith("local_"):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
            normalized[name] = value
        else:
            normalized[name] = _json_number(value, name)
    return normalized


def _approved_history_skip_reason(reason: str | None) -> str:
    if reason in _HISTORY_SKIP_REASONS:
        return reason
    return PredictionSkipReason.INCOMPLETE_FEATURE_HISTORY.value


def _json_number(value: object, name: str) -> int | float:
    decimal = _as_decimal(value, name)
    if decimal == decimal.to_integral_value():
        return int(decimal)
    converted = float(decimal)
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be finite")
    return converted


def _as_decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValueError(f"{name} must be numeric") from error
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def _require_aware_datetime(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone offset")


def _strictly_before_time(
    observation: FeatureObservation,
    anchor_time: datetime,
    *,
    anchor_time_precision: str,
) -> bool:
    if observation.event_time >= anchor_time:
        return False
    same_minute = _utc_minute(observation.event_time) == _utc_minute(anchor_time)
    return not (same_minute and "minute" in (observation.time_precision, anchor_time_precision))


def _utc_minute(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(second=0, microsecond=0)
