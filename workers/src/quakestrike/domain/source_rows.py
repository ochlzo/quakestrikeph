"""Immutable normalized observations from PHIVOLCS source pages."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType


class SourceTimePrecision(StrEnum):
    """Precision PHIVOLCS supplied for an event timestamp."""

    MINUTE = "minute"
    SECOND = "second"


class DiagnosticCode(StrEnum):
    """Stable, persistence-safe reasons for source normalization outcomes."""

    INVALID_NUMERIC_VALUE = "INVALID_NUMERIC_VALUE"
    INVALID_CATALOG_TIMESTAMP = "INVALID_CATALOG_TIMESTAMP"
    INVALID_CATALOG_ROW = "INVALID_CATALOG_ROW"
    INVALID_SOURCE_URL = "INVALID_SOURCE_URL"
    DETAIL_FETCH_FAILED = "DETAIL_FETCH_FAILED"
    DETAIL_NON_HTML_RESPONSE = "DETAIL_NON_HTML_RESPONSE"
    DETAIL_DECODE_FAILED = "DETAIL_DECODE_FAILED"
    DETAIL_TIMESTAMP_MISSING = "DETAIL_TIMESTAMP_MISSING"
    DETAIL_TIMESTAMP_MISMATCH = "DETAIL_TIMESTAMP_MISMATCH"
    DETAIL_ORIGIN_MISSING = "DETAIL_ORIGIN_MISSING"
    DETAIL_ORIGIN_UNKNOWN = "DETAIL_ORIGIN_UNKNOWN"


@dataclass(frozen=True, slots=True)
class SourceDiagnostic:
    """A diagnostic that is safe to persist or emit in structured logs."""

    code: DiagnosticCode
    context: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        sanitized: dict[str, str] = {}
        for key, value in self.context.items():
            if key not in {"field", "asset_type", "status", "failure_kind"}:
                raise ValueError("diagnostic context key is invalid")
            text = str(value)
            if (
                len(text) > 48
                or not re.fullmatch(r"[a-z0-9_]+", text)
                or any(marker in text for marker in ("http", "secret", "token", "password"))
            ):
                raise ValueError("diagnostic context value is invalid")
            sanitized[key] = text
        object.__setattr__(self, "context", MappingProxyType(sanitized))


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Canonical PHIVOLCS bulletin identity extracted from a source link."""

    source_url: str
    source_bulletin_id: str | None
    source_event_group_id: str


@dataclass(frozen=True, slots=True)
class RejectedSourceRow:
    """One catalog row rejected without stopping a valid catalog response."""

    row_number: int
    diagnostic: SourceDiagnostic


@dataclass(frozen=True, slots=True)
class CatalogParseResult:
    """Ordered accepted and rejected results from a current catalog page."""

    accepted_rows: tuple[NormalizedSourceRow, ...]
    rejected_rows: tuple[RejectedSourceRow, ...]


_GROUP_ID_PATTERN = re.compile(r"^\d{4}_\d{3,4}_\d{4,8}$")
_BULLETIN_ID_PATTERN = re.compile(r"^(?P<group>\d{4}_\d{3,4}_\d{4,8})_B[^_]+$")
_MAX_DEPTH_KM = Decimal("9999999.999")


@dataclass(frozen=True, slots=True)
class NormalizedSourceRow:
    """A validated PHIVOLCS catalog observation before reconciliation."""

    occurred_at: datetime
    time_precision: SourceTimePrecision
    latitude: Decimal
    longitude: Decimal
    depth_km: Decimal
    magnitude: Decimal
    location_description: str
    source_bulletin_id: str | None
    source_event_group_id: str | None
    source_url: str
    origin: str | None = None
    diagnostics: tuple[SourceDiagnostic, ...] = ()

    @classmethod
    def from_catalog_values(
        cls,
        *,
        occurred_at: datetime,
        latitude: str | Decimal,
        longitude: str | Decimal,
        depth_km: str | Decimal,
        magnitude: str | Decimal,
        location_description: str,
        source_bulletin_id: str | None,
        source_event_group_id: str | None,
        source_url: str,
    ) -> NormalizedSourceRow:
        """Build a minute-precision row from validated catalog fields."""

        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone offset")
        location = " ".join(location_description.split())
        if not location:
            raise ValueError("location_description must not be blank")
        if not source_url:
            raise ValueError("source_url must not be blank")

        normalized_group = _normalize_group_id(source_event_group_id)
        normalized_bulletin = _normalize_bulletin_id(source_bulletin_id)
        if normalized_bulletin is not None:
            bulletin_group = _BULLETIN_ID_PATTERN.fullmatch(normalized_bulletin)
            assert bulletin_group is not None
            if normalized_group is None:
                normalized_group = bulletin_group.group("group")
            elif normalized_group != bulletin_group.group("group"):
                raise ValueError("source identifiers disagree")

        return cls(
            occurred_at=occurred_at.replace(second=0, microsecond=0),
            time_precision=SourceTimePrecision.MINUTE,
            latitude=_quantize_coordinate(latitude, Decimal("0.000001"), -90, 90, "latitude"),
            longitude=_quantize_coordinate(longitude, Decimal("0.000001"), -180, 180, "longitude"),
            depth_km=_quantize_nonnegative(depth_km, Decimal("0.001"), "depth_km"),
            magnitude=_quantize_magnitude(magnitude),
            location_description=location,
            source_bulletin_id=normalized_bulletin,
            source_event_group_id=normalized_group,
            source_url=source_url,
        )

    def with_detail_enrichment(
        self,
        *,
        detail_occurred_at: datetime | None,
        origin: str | None,
        diagnostics: tuple[SourceDiagnostic, ...],
    ) -> NormalizedSourceRow:
        """Accept detail seconds only when they describe this catalog minute."""

        combined_diagnostics = list(self.diagnostics) + list(diagnostics)
        if detail_occurred_at is None:
            return replace(self, origin=origin, diagnostics=tuple(combined_diagnostics))

        catalog_local = self.occurred_at.astimezone(detail_occurred_at.tzinfo)
        if (
            catalog_local.date(),
            catalog_local.hour,
            catalog_local.minute,
        ) != (
            detail_occurred_at.date(),
            detail_occurred_at.hour,
            detail_occurred_at.minute,
        ):
            combined_diagnostics.append(SourceDiagnostic(DiagnosticCode.DETAIL_TIMESTAMP_MISMATCH))
            return replace(self, origin=origin, diagnostics=tuple(combined_diagnostics))
        return replace(
            self,
            occurred_at=detail_occurred_at.replace(microsecond=0),
            time_precision=SourceTimePrecision.SECOND,
            origin=origin,
            diagnostics=tuple(combined_diagnostics),
        )


def _decimal(value: str | Decimal, field_name: str) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name} must be decimal") from error
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _quantize_coordinate(
    value: str | Decimal,
    scale: Decimal,
    lower_bound: int,
    upper_bound: int,
    field_name: str,
) -> Decimal:
    parsed = _decimal(value, field_name)
    if not Decimal(lower_bound) <= parsed <= Decimal(upper_bound):
        raise ValueError(f"{field_name} is out of range")
    return parsed.quantize(scale, rounding=ROUND_HALF_EVEN)


def _quantize_nonnegative(value: str | Decimal, scale: Decimal, field_name: str) -> Decimal:
    parsed = _decimal(value, field_name)
    if not Decimal(0) <= parsed <= _MAX_DEPTH_KM:
        raise ValueError(f"{field_name} must not be negative")
    try:
        return parsed.quantize(scale, rounding=ROUND_HALF_EVEN)
    except InvalidOperation as error:
        raise ValueError(f"{field_name} cannot be quantized") from error


def _quantize_magnitude(value: str | Decimal) -> Decimal:
    parsed = _decimal(value, "magnitude")
    if not Decimal("-999.99") <= parsed <= Decimal("999.99"):
        raise ValueError("magnitude is out of range")
    return parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _normalize_group_id(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    result = value.strip().upper()
    if not _GROUP_ID_PATTERN.fullmatch(result):
        raise ValueError("source_event_group_id is invalid")
    return result


def _normalize_bulletin_id(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    result = value.strip().upper()
    if not _BULLETIN_ID_PATTERN.fullmatch(result):
        raise ValueError("source_bulletin_id is invalid")
    return result
