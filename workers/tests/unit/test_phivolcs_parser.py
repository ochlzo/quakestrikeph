from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from quakestrike.domain.source_rows import DiagnosticCode, SourceTimePrecision
from quakestrike.infrastructure.phivolcs.parser import parse_current_catalog

FIXTURES = Path(__file__).parents[1] / "fixtures" / "phivolcs"
CATALOG_URL = "https://earthquake.phivolcs.dost.gov.ph/"


def test_parse_current_catalog_returns_normalized_rows_and_row_diagnostics() -> None:
    result = parse_current_catalog((FIXTURES / "current_catalog.html").read_bytes(), CATALOG_URL)

    assert len(result.accepted_rows) == 1
    assert len(result.rejected_rows) == 1
    row = result.accepted_rows[0]
    assert row.time_precision is SourceTimePrecision.MINUTE
    assert row.latitude == Decimal("10.123457")
    assert row.longitude == Decimal("125.987655")
    assert row.depth_km == Decimal("7.124")
    assert row.magnitude == Decimal("4.26")
    assert row.location_description == "76 \N{DEGREE SIGN} W of Test"
    assert row.source_bulletin_id == "2025_0102_0304_B1"
    assert result.rejected_rows[0].diagnostic.code is DiagnosticCode.INVALID_NUMERIC_VALUE
