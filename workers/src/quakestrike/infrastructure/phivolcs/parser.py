"""Pure parsing of PHIVOLCS current catalogs and bulletin detail pages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from quakestrike.domain.source_rows import (
    CatalogParseResult,
    DiagnosticCode,
    NormalizedSourceRow,
    RejectedSourceRow,
    SourceDiagnostic,
)
from quakestrike.infrastructure.phivolcs.urls import BulletinUrlRejected, canonicalize_bulletin_url

MANILA = ZoneInfo("Asia/Manila")
_CATALOG_TIME_FORMATS = ("%d %B %Y - %I:%M %p", "%d %b %Y - %I:%M %p")
_DETAIL_TIME_FORMATS = ("%d %B %Y - %I:%M:%S %p", "%d %b %Y - %I:%M:%S %p")


class CatalogStructuralError(ValueError):
    """The catalog body cannot be treated as a current PHIVOLCS catalog."""


@dataclass(frozen=True, slots=True)
class ParsedDetail:
    """Data a bulletin detail page supplied without making it authoritative."""

    occurred_at: datetime | None
    origin: str | None
    diagnostics: tuple[SourceDiagnostic, ...]


def parse_current_catalog(body: bytes | str, page_url: str) -> CatalogParseResult:
    """Normalize current-page rows and retain diagnostics for rejected rows."""

    html = _decode_html(body, failure="catalog")
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        raise CatalogStructuralError("catalog does not contain a table")

    accepted: list[NormalizedSourceRow] = []
    rejected: list[RejectedSourceRow] = []
    candidate_rows = 0
    row_number = 0
    for table in tables:
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"], recursive=False)
            if not cells or all(cell.name == "th" for cell in cells):
                continue
            row_number += 1
            if len(cells) != 6:
                rejected.append(
                    RejectedSourceRow(
                        row_number,
                        SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW),
                    )
                )
                continue
            candidate_rows += 1
            try:
                accepted.append(_parse_catalog_row(cells, page_url))
            except BulletinUrlRejected:
                rejected.append(
                    RejectedSourceRow(
                        row_number,
                        SourceDiagnostic(
                            DiagnosticCode.INVALID_SOURCE_URL, {"field": "source_url"}
                        ),
                    )
                )
            except ValueError as error:
                rejected.append(RejectedSourceRow(row_number, _row_diagnostic(error)))

    if candidate_rows == 0:
        raise CatalogStructuralError("catalog does not contain event rows")
    return CatalogParseResult(tuple(accepted), tuple(rejected))


def parse_detail_page(body: bytes | str) -> ParsedDetail:
    """Extract optional seconds and origin from a detail page without raising."""

    try:
        html = _decode_html(body, failure="detail")
    except CatalogStructuralError:
        return ParsedDetail(None, None, (SourceDiagnostic(DiagnosticCode.DETAIL_DECODE_FAILED),))
    soup = BeautifulSoup(html, "html.parser")
    date_time: str | None = None
    origin_value: str | None = None
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) != 2:
            continue
        label = _clean_text(cells[0].get_text(" ", strip=True)).rstrip(":").strip().casefold()
        value = _clean_text(cells[1].get_text(" ", strip=True))
        if label.startswith("date/time"):
            date_time = value
        elif label == "origin":
            origin_value = value

    diagnostics: list[SourceDiagnostic] = []
    occurred_at = _parse_detail_time(date_time)
    if occurred_at is None:
        diagnostics.append(SourceDiagnostic(DiagnosticCode.DETAIL_TIMESTAMP_MISSING))
    origin = normalize_detail_origin(origin_value, diagnostics)
    return ParsedDetail(occurred_at, origin, tuple(diagnostics))


def _parse_catalog_row(cells: list[object], page_url: str) -> NormalizedSourceRow:
    values = [_clean_text(cell.get_text(" ", strip=True)) for cell in cells]  # type: ignore[attr-defined]
    date_text, latitude, longitude, depth, magnitude, location = values
    occurred_at = _parse_catalog_time(date_text)
    link = _event_link(cells[0], date_text)
    if link is None:
        raise BulletinUrlRejected("catalog event has no detail link")
    identity = canonicalize_bulletin_url(page_url, str(link["href"]), occurred_at.year)  # type: ignore[index]
    return NormalizedSourceRow.from_catalog_values(
        occurred_at=occurred_at.replace(tzinfo=MANILA),
        latitude=latitude,
        longitude=longitude,
        depth_km=depth,
        magnitude=magnitude,
        location_description=location,
        source_bulletin_id=identity.source_bulletin_id,
        source_event_group_id=identity.source_event_group_id,
        source_url=identity.source_url,
    )


def _parse_catalog_time(value: str) -> datetime:
    for time_format in _CATALOG_TIME_FORMATS:
        try:
            return datetime.strptime(value, time_format)
        except ValueError:
            continue
    raise ValueError("catalog timestamp is invalid")


def _parse_detail_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    for time_format in _DETAIL_TIME_FORMATS:
        try:
            return datetime.strptime(value, time_format).replace(tzinfo=MANILA)
        except ValueError:
            continue
    return None


def _event_link(cell: object, date_text: str) -> object | None:
    links = cell.find_all("a", href=True)  # type: ignore[attr-defined]
    if not links:
        return None
    displayed_time = date_text.rsplit(" - ", 1)[-1]
    matching = [
        link for link in links if displayed_time in _clean_text(link.get_text(" ", strip=True))
    ]
    return matching[-1] if matching else links[0]


def _decode_html(body: bytes | str, *, failure: str) -> str:
    if isinstance(body, str):
        return body
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return body.decode("cp1252")
        except UnicodeDecodeError as error:
            raise CatalogStructuralError(f"{failure} body cannot be decoded") from error


def _clean_text(value: str) -> str:
    return " ".join(value.split()).replace("Â°", "°")


def _row_diagnostic(error: ValueError) -> SourceDiagnostic:
    message = str(error)
    if "timestamp" in message:
        return SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_TIMESTAMP, {"field": "event_time"})
    if any(field in message for field in ("latitude", "longitude", "depth_km", "magnitude")):
        return SourceDiagnostic(DiagnosticCode.INVALID_NUMERIC_VALUE)
    return SourceDiagnostic(DiagnosticCode.INVALID_CATALOG_ROW)


def normalize_detail_origin(value: str | None, diagnostics: list[SourceDiagnostic]) -> str | None:
    """Apply the bounded origin vocabulary used by live detail parsing."""

    if value is None or not value.strip():
        diagnostics.append(SourceDiagnostic(DiagnosticCode.DETAIL_ORIGIN_MISSING))
        return None
    normalized = " ".join(value.upper().replace("_", "-").split())
    normalized = normalized.replace(" - ", "-")
    if normalized in {"TECTONIC", "VOLCANIC", "TECTONIC-VOLCANIC"}:
        return normalized
    diagnostics.append(SourceDiagnostic(DiagnosticCode.DETAIL_ORIGIN_UNKNOWN))
    return None
