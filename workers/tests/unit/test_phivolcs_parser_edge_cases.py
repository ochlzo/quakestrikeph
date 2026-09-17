from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from quakestrike.domain.source_rows import DiagnosticCode, NormalizedSourceRow
from quakestrike.infrastructure.phivolcs.parser import (
    CatalogStructuralError,
    parse_current_catalog,
    parse_detail_page,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "phivolcs"
CATALOG_URL = "https://earthquake.phivolcs.dost.gov.ph/"


def test_catalog_parser_accepts_utf8_bom_cp1252_and_abbreviated_months() -> None:
    html = (FIXTURES / "current_catalog.html").read_text(encoding="utf-8")
    abbreviated = html.replace("02 January 2025", "02 Jan 2025")

    bom_result = parse_current_catalog(b"\xef\xbb\xbf" + abbreviated.encode("utf-8"), CATALOG_URL)
    cp1252_result = parse_current_catalog(abbreviated.encode("cp1252"), CATALOG_URL)

    assert bom_result.accepted_rows[0].occurred_at.month == 1
    assert cp1252_result.accepted_rows[0].location_description == "76 \N{DEGREE SIGN} W of Test"


def test_catalog_parser_rejects_missing_link_but_stops_for_undecodable_or_empty_catalogs() -> None:
    html = (FIXTURES / "current_catalog.html").read_text(encoding="utf-8")
    missing_link = html.replace(
        ' href="2025_Earthquake_Information\\\\January\\\\2025_0102_0304_B1.html"', ""
    )

    result = parse_current_catalog(missing_link, CATALOG_URL)

    assert result.rejected_rows[0].diagnostic.code is DiagnosticCode.INVALID_SOURCE_URL
    with pytest.raises(CatalogStructuralError):
        parse_current_catalog(b"\xff\x81", CATALOG_URL)
    with pytest.raises(CatalogStructuralError):
        parse_current_catalog("<table><tr><th>Header</th></tr></table>", CATALOG_URL)


@pytest.mark.parametrize("cell_count", [5, 7])
def test_catalog_parser_reports_visible_malformed_rows_without_losing_valid_siblings(
    cell_count: int,
) -> None:
    cells = "".join("<td>broken</td>" for _ in range(cell_count))
    html = (
        "<table>"
        "<tr><th>Date</th></tr>"
        "<tr><td><a href='2025_Earthquake_Information/January/2025_0102_0304_B1.html'>"
        "02 January 2025 - 11:04 AM</a></td><td>10</td><td>125</td><td>7</td>"
        "<td>4.2</td><td>Test location</td></tr>"
        f"<tr>{cells}</tr>"
        "</table>"
    )

    result = parse_current_catalog(html, CATALOG_URL)

    assert len(result.accepted_rows) == 1
    assert len(result.rejected_rows) == 1
    assert result.rejected_rows[0].row_number == 2
    assert result.rejected_rows[0].diagnostic.code is DiagnosticCode.INVALID_CATALOG_ROW


def test_catalog_parser_treats_an_all_malformed_table_as_suspicious() -> None:
    html = "<table><tr><th>Date</th></tr><tr><td>broken</td><td>row</td></tr></table>"

    with pytest.raises(CatalogStructuralError):
        parse_current_catalog(html, CATALOG_URL)


def test_catalog_parser_rejects_each_invalid_depth_without_losing_a_valid_sibling() -> None:
    def row(number: int, depth: str) -> str:
        return (
            "<tr><td><a href='2025_Earthquake_Information/January/"
            f"2025_0102_03{number:02}_B1.html'>02 January 2025 - 11:{number:02} AM</a></td>"
            f"<td>10</td><td>125</td><td>{depth}</td><td>4.2</td><td>Test location</td></tr>"
        )

    html = (
        "<table>"
        + row(4, "7")
        + "".join(
            row(number, depth)
            for number, depth in enumerate(("9999999.9994", "10000000", "1e100"), start=5)
        )
        + "</table>"
    )

    result = parse_current_catalog(html, CATALOG_URL)

    assert len(result.accepted_rows) == 1
    assert [row.diagnostic.code for row in result.rejected_rows] == [
        DiagnosticCode.INVALID_NUMERIC_VALUE,
        DiagnosticCode.INVALID_NUMERIC_VALUE,
        DiagnosticCode.INVALID_NUMERIC_VALUE,
    ]


def test_detail_parser_normalizes_known_origins_and_reports_missing_or_unknown_values() -> None:
    known = parse_detail_page(
        "<table><tr><td>Date/Time :</td><td>02 Jan 2025 - 11:04:37 AM</td></tr>"
        "<tr><td>Origin :</td><td>tectonic-volcanic</td></tr></table>"
    )
    missing = parse_detail_page("<table><tr><td>Date/Time :</td><td>not a date</td></tr></table>")
    unknown = parse_detail_page("<table><tr><td>Origin :</td><td>induced</td></tr></table>")

    assert known.origin == "TECTONIC-VOLCANIC"
    assert known.occurred_at is not None and known.occurred_at.second == 37
    assert DiagnosticCode.DETAIL_ORIGIN_MISSING in {
        diagnostic.code for diagnostic in missing.diagnostics
    }
    assert DiagnosticCode.DETAIL_ORIGIN_UNKNOWN in {
        diagnostic.code for diagnostic in unknown.diagnostics
    }


def test_source_time_represents_manila_local_time_across_a_utc_date_boundary() -> None:
    row = NormalizedSourceRow.from_catalog_values(
        occurred_at=datetime.fromisoformat("2025-01-01T00:05:00+08:00"),
        latitude="10",
        longitude="125",
        depth_km="7",
        magnitude="4.2",
        location_description="Test location",
        source_bulletin_id="2025_0101_0005_B1",
        source_event_group_id="2025_0101_0005",
        source_url="https://earthquake.phivolcs.dost.gov.ph/2025_Earthquake_Information/January/2025_0101_0005_B1.html",
    )

    assert row.occurred_at.astimezone(UTC) == datetime(2024, 12, 31, 16, 5, tzinfo=UTC)
