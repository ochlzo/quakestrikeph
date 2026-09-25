from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from quakestrike.domain.source_rows import (
    DiagnosticCode,
    NormalizedSourceRow,
    SourceDiagnostic,
    SourceTimePrecision,
)


def test_normalized_source_row_preserves_catalog_minute_precision_and_quantizes_values() -> None:
    row = NormalizedSourceRow.from_catalog_values(
        occurred_at=datetime(2025, 1, 2, 11, 4, tzinfo=ZoneInfo("Asia/Manila")),
        latitude="10.1234567",
        longitude="125.9876547",
        depth_km="7.1236",
        magnitude="4.255",
        location_description="76 A\N{DEGREE SIGN} W of Test",
        source_bulletin_id="2025_0102_0304_b1_nl",
        source_event_group_id="2025_0102_0304",
        source_url=(
            "https://earthquake.phivolcs.dost.gov.ph/2025_Earthquake_Information/"
            "January/2025_0102_0304_B1_NL.html"
        ),
    )

    assert row.occurred_at.utcoffset() is not None
    assert row.time_precision is SourceTimePrecision.MINUTE
    assert row.latitude == Decimal("10.123457")
    assert row.longitude == Decimal("125.987655")
    assert row.depth_km == Decimal("7.124")
    assert row.magnitude == Decimal("4.26")
    assert row.source_bulletin_id == "2025_0102_0304_B1_NL"
    assert row.source_event_group_id == "2025_0102_0304"


def test_normalized_source_row_uses_half_even_decimal_quantization() -> None:
    row = NormalizedSourceRow.from_catalog_values(
        occurred_at=datetime(2025, 1, 2, 11, 4, tzinfo=ZoneInfo("Asia/Manila")),
        latitude="10",
        longitude="125",
        depth_km="7",
        magnitude="4.245",
        location_description="Test location",
        source_bulletin_id="2025_0102_0304_B1",
        source_event_group_id="2025_0102_0304",
        source_url=(
            "https://earthquake.phivolcs.dost.gov.ph/2025_Earthquake_Information/"
            "January/2025_0102_0304_B1.html"
        ),
    )

    assert row.magnitude == Decimal("4.24")


def test_normalized_source_row_accepts_only_database_representable_depths() -> None:
    values: dict[str, object] = {
        "occurred_at": datetime(2025, 1, 2, 11, 4, tzinfo=ZoneInfo("Asia/Manila")),
        "latitude": "10",
        "longitude": "125",
        "depth_km": "9999999.999",
        "magnitude": "4.2",
        "location_description": "Test location",
        "source_bulletin_id": "2025_0102_0304_B1",
        "source_event_group_id": "2025_0102_0304",
        "source_url": "https://earthquake.phivolcs.dost.gov.ph/2025_Earthquake_Information/January/2025_0102_0304_B1.html",
    }

    row = NormalizedSourceRow.from_catalog_values(**values)  # type: ignore[arg-type]

    assert row.depth_km == Decimal("9999999.999")
    for invalid_depth in ("9999999.9994", "10000000", "1e100"):
        values["depth_km"] = invalid_depth
        with pytest.raises(ValueError):
            NormalizedSourceRow.from_catalog_values(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude", "NaN"),
        ("longitude", "Infinity"),
        ("depth_km", "-0.001"),
        ("latitude", "90.0000004"),
        ("magnitude", "1000"),
    ],
)
def test_normalized_source_row_rejects_nonfinite_or_out_of_range_values(
    field: str, value: str
) -> None:
    values: dict[str, object] = {
        "occurred_at": datetime(2025, 1, 2, 11, 4, tzinfo=ZoneInfo("Asia/Manila")),
        "latitude": "10",
        "longitude": "125",
        "depth_km": "7",
        "magnitude": "4.2",
        "location_description": "Test location",
        "source_bulletin_id": "2025_0102_0304_B1",
        "source_event_group_id": "2025_0102_0304",
        "source_url": "https://earthquake.phivolcs.dost.gov.ph/2025_Earthquake_Information/January/2025_0102_0304_B1.html",
    }
    values[field] = value

    with pytest.raises(ValueError):
        NormalizedSourceRow.from_catalog_values(**values)  # type: ignore[arg-type]


def test_source_diagnostic_rejects_url_or_multiline_context() -> None:
    with pytest.raises(ValueError):
        SourceDiagnostic(
            DiagnosticCode.DETAIL_FETCH_FAILED,
            {"reason": "https://user:password@example.invalid/path?secret=1"},
        )
    with pytest.raises(ValueError):
        SourceDiagnostic(DiagnosticCode.DETAIL_FETCH_FAILED, {"reason": "line one\nline two"})
