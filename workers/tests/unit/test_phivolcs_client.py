from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
import requests

from quakestrike.application.phivolcs import CatalogRetrievalError, CatalogRetrievalLeaseLost
from quakestrike.domain.source_rows import DiagnosticCode, SourceTimePrecision
from quakestrike.infrastructure.phivolcs.client import (
    PhivolcsCatalogClient,
    validated_catalog_evidence,
)
from quakestrike.infrastructure.phivolcs.parser import parse_current_catalog

FIXTURES = Path(__file__).parents[1] / "fixtures" / "phivolcs"
CATALOG_URL = "https://earthquake.phivolcs.dost.gov.ph/"


def test_current_month_catalog_proves_coverage_only_when_all_event_rows_parse() -> None:
    body = b"""<html><strong>SEPTEMBER 2026</strong><table>
      <tr><th>Date</th><th>Latitude</th><th>Longitude</th><th>Depth</th><th>Mag</th><th>Location</th></tr>
      <tr><td><a href="2026_Earthquake_Information/September/2026_0901_0009_B1.html">
        01 September 2026 - 08:09 AM</a></td>
        <td>10</td><td>125</td><td>7</td><td>2.0</td><td>Test</td></tr>
      <tr><td><a href="2026_Earthquake_Information/September/2026_0902_0100_B1.html">
        02 September 2026 - 09:00 AM</a></td>
        <td>10</td><td>125</td><td>7</td><td>2.0</td><td>Test</td></tr>
    </table></html>"""
    fetched_at = datetime(2026, 9, 2, 2, tzinfo=UTC)
    parsed = parse_current_catalog(body, CATALOG_URL)

    evidence = validated_catalog_evidence(parsed, CATALOG_URL, body, fetched_at)

    assert evidence is not None
    assert evidence.coverage_start.isoformat() == "2026-09-01T00:00:00+08:00"
    assert evidence.coverage_end == fetched_at
    malformed = body.replace(b"<td>2.0</td>", b"<td>NaN</td>", 1)
    assert (
        validated_catalog_evidence(
            parse_current_catalog(malformed, CATALOG_URL), CATALOG_URL, malformed, fetched_at
        )
        is None
    )


class ScriptedResponse:
    def __init__(
        self, body: bytes, *, status_code: int = 200, content_type: str = "text/html"
    ) -> None:
        self.body = body
        self.status_code = status_code
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(body))}

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [
            self.body[index : index + chunk_size] for index in range(0, len(self.body), chunk_size)
        ]

    def close(self) -> None:
        pass


class StreamingFailureResponse(ScriptedResponse):
    def iter_content(self, chunk_size: int) -> list[bytes]:
        raise requests.exceptions.ConnectionError("connection reset")


class ScriptedSession:
    def __init__(self, responses: list[ScriptedResponse | requests.RequestException]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> ScriptedResponse:
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, requests.RequestException):
            raise response
        return response


def test_bounded_detail_fetch_uses_separate_sessions_and_preserves_row_order() -> None:
    rows_html = "".join(
        f'<tr><td><a href="2026_Earthquake_Information/September/'
        f'2026_0901_0{i:03d}_B1.html">01 September 2026 - 08:0{i} AM</a></td>'
        "<td>10</td><td>125</td><td>7</td><td>2.0</td><td>Test</td></tr>"
        for i in range(4)
    )
    rows = parse_current_catalog(f"<table>{rows_html}</table>", CATALOG_URL).accepted_rows
    rendezvous = Barrier(4)
    sessions = []

    class DetailSession:
        closed = False

        def get(self, url: str, **kwargs: object) -> ScriptedResponse:
            rendezvous.wait(timeout=2)
            return ScriptedResponse((FIXTURES / "bulletin_detail.html").read_bytes())

        def close(self) -> None:
            self.closed = True

    def make_session() -> DetailSession:
        session = DetailSession()
        sessions.append(session)
        return session

    client = PhivolcsCatalogClient(
        catalog_url=CATALOG_URL,
        session=ScriptedSession([]),
        max_response_bytes=10_000,
        connect_timeout_seconds=3,
        read_timeout_seconds=4,
        detail_delay_seconds=0,
        detail_concurrency=4,
        detail_session_factory=make_session,
    )

    enriched = client.enrich_rows((*rows, rows[0]), heartbeat=lambda: True)

    assert [row.source_bulletin_id for row in enriched] == [
        *(row.source_bulletin_id for row in rows),
        rows[0].source_bulletin_id,
    ]
    assert len(sessions) == 4
    assert all(session.closed for session in sessions)
    sessions.clear()
    with pytest.raises(CatalogRetrievalLeaseLost):
        client.enrich_rows(rows, heartbeat=lambda: False)
    assert sessions == []


def test_retrieve_current_catalog_reuses_one_detail_download_and_validates_each_row() -> None:
    session = ScriptedSession(
        [
            ScriptedResponse((FIXTURES / "current_catalog_duplicate_detail.html").read_bytes()),
            ScriptedResponse((FIXTURES / "bulletin_detail.html").read_bytes()),
        ]
    )
    pauses: list[float] = []
    client = PhivolcsCatalogClient(
        catalog_url=CATALOG_URL,
        session=session,
        max_response_bytes=10_000,
        connect_timeout_seconds=3,
        read_timeout_seconds=4,
        detail_delay_seconds=0.1,
        sleep=pauses.append,
    )

    result = client.retrieve_current_catalog()

    assert len(session.calls) == 2
    assert len(result.accepted_rows) == 2
    assert result.accepted_rows[0].time_precision is SourceTimePrecision.SECOND
    assert result.accepted_rows[0].origin == "VOLCANIC"
    assert result.accepted_rows[1].time_precision is SourceTimePrecision.MINUTE
    assert DiagnosticCode.DETAIL_TIMESTAMP_MISMATCH in {
        diagnostic.code for diagnostic in result.accepted_rows[1].diagnostics
    }
    assert pauses == []
    assert session.calls[0][1]["timeout"] == (3, 4)
    assert session.calls[0][1]["stream"] is True
    assert session.calls[0][1]["allow_redirects"] is False


def test_detail_non_html_response_keeps_catalog_row_with_sanitized_diagnostic() -> None:
    session = ScriptedSession(
        [
            ScriptedResponse((FIXTURES / "current_catalog.html").read_bytes()),
            ScriptedResponse(b"not html", content_type="application/pdf"),
        ]
    )
    client = PhivolcsCatalogClient(
        catalog_url=CATALOG_URL,
        session=session,
        max_response_bytes=10_000,
        connect_timeout_seconds=3,
        read_timeout_seconds=4,
        detail_delay_seconds=0,
    )

    result = client.retrieve_current_catalog()

    row = result.accepted_rows[0]
    assert row.time_precision is SourceTimePrecision.MINUTE
    assert row.origin is None
    assert DiagnosticCode.DETAIL_NON_HTML_RESPONSE in {
        diagnostic.code for diagnostic in row.diagnostics
    }


def test_oversized_or_terminal_catalog_response_stops_the_retrieval() -> None:
    oversized = ScriptedResponse((FIXTURES / "current_catalog.html").read_bytes())
    oversized.headers["Content-Length"] = "10001"
    client = PhivolcsCatalogClient(
        catalog_url=CATALOG_URL,
        session=ScriptedSession([oversized]),
        max_response_bytes=10_000,
        connect_timeout_seconds=3,
        read_timeout_seconds=4,
        detail_delay_seconds=0,
    )

    with pytest.raises(CatalogRetrievalError):
        client.retrieve_current_catalog()

    dishonest = ScriptedResponse(b"x" * 10_001)
    dishonest.headers["Content-Length"] = "1"
    dishonest_client = PhivolcsCatalogClient(
        catalog_url=CATALOG_URL,
        session=ScriptedSession([dishonest]),
        max_response_bytes=10_000,
        connect_timeout_seconds=3,
        read_timeout_seconds=4,
        detail_delay_seconds=0,
    )
    with pytest.raises(CatalogRetrievalError):
        dishonest_client.retrieve_current_catalog()


def test_detail_tls_failure_keeps_valid_catalog_data_and_catalog_tls_failure_stops() -> None:
    catalog = ScriptedResponse((FIXTURES / "current_catalog.html").read_bytes())
    client = PhivolcsCatalogClient(
        catalog_url=CATALOG_URL,
        session=ScriptedSession([catalog, requests.exceptions.SSLError("certificate failure")]),
        max_response_bytes=10_000,
        connect_timeout_seconds=3,
        read_timeout_seconds=4,
        detail_delay_seconds=0,
    )

    result = client.retrieve_current_catalog()

    assert result.accepted_rows[0].time_precision is SourceTimePrecision.MINUTE
    assert DiagnosticCode.DETAIL_FETCH_FAILED in {
        diagnostic.code for diagnostic in result.accepted_rows[0].diagnostics
    }
    failing_catalog = PhivolcsCatalogClient(
        catalog_url=CATALOG_URL,
        session=ScriptedSession([requests.exceptions.SSLError("certificate failure")]),
        max_response_bytes=10_000,
        connect_timeout_seconds=3,
        read_timeout_seconds=4,
        detail_delay_seconds=0,
    )
    with pytest.raises(CatalogRetrievalError):
        failing_catalog.retrieve_current_catalog()


def test_detail_streaming_failure_keeps_catalog_data_with_a_fetch_diagnostic() -> None:
    client = PhivolcsCatalogClient(
        catalog_url=CATALOG_URL,
        session=ScriptedSession(
            [
                ScriptedResponse((FIXTURES / "current_catalog.html").read_bytes()),
                StreamingFailureResponse(b""),
            ]
        ),
        max_response_bytes=10_000,
        connect_timeout_seconds=3,
        read_timeout_seconds=4,
        detail_delay_seconds=0,
    )

    result = client.retrieve_current_catalog()

    assert result.accepted_rows[0].time_precision is SourceTimePrecision.MINUTE
    assert DiagnosticCode.DETAIL_FETCH_FAILED in {
        diagnostic.code for diagnostic in result.accepted_rows[0].diagnostics
    }


def test_detail_requests_are_sequential_with_a_delay_only_between_unique_urls() -> None:
    catalog = (FIXTURES / "current_catalog_duplicate_detail.html").read_text(encoding="utf-8")
    catalog = catalog.replace(
        '2025_0102_0304_B1.html">02 January 2025 - 11:05 AM',
        '2025_0102_0305_B1.html">02 January 2025 - 11:05 AM',
    )
    session = ScriptedSession(
        [
            ScriptedResponse(catalog.encode()),
            ScriptedResponse((FIXTURES / "bulletin_detail.html").read_bytes()),
            ScriptedResponse((FIXTURES / "bulletin_detail.html").read_bytes()),
        ]
    )
    pauses: list[float] = []
    client = PhivolcsCatalogClient(
        catalog_url=CATALOG_URL,
        session=session,
        max_response_bytes=10_000,
        connect_timeout_seconds=3,
        read_timeout_seconds=4,
        detail_delay_seconds=0.1,
        sleep=pauses.append,
    )

    client.retrieve_current_catalog()

    assert len(session.calls) == 3
    assert pauses == [0.1]


def test_retrieval_heartbeats_between_catalog_and_each_detail_request() -> None:
    catalog = (FIXTURES / "current_catalog_duplicate_detail.html").read_text(encoding="utf-8")
    catalog = catalog.replace(
        '2025_0102_0304_B1.html">02 January 2025 - 11:05 AM',
        '2025_0102_0305_B1.html">02 January 2025 - 11:05 AM',
    )
    client = PhivolcsCatalogClient(
        catalog_url=CATALOG_URL,
        session=ScriptedSession(
            [
                ScriptedResponse(catalog.encode()),
                ScriptedResponse((FIXTURES / "bulletin_detail.html").read_bytes()),
                ScriptedResponse((FIXTURES / "bulletin_detail.html").read_bytes()),
            ]
        ),
        max_response_bytes=10_000,
        connect_timeout_seconds=3,
        read_timeout_seconds=4,
        detail_delay_seconds=0,
    )
    heartbeats = 0

    def heartbeat() -> bool:
        nonlocal heartbeats
        heartbeats += 1
        return True

    client.retrieve_current_catalog(heartbeat=heartbeat)

    assert heartbeats >= 5


def test_retrieval_stops_when_the_lease_is_lost_before_a_detail_request() -> None:
    client = PhivolcsCatalogClient(
        catalog_url=CATALOG_URL,
        session=ScriptedSession(
            [ScriptedResponse((FIXTURES / "current_catalog.html").read_bytes())]
        ),
        max_response_bytes=10_000,
        connect_timeout_seconds=3,
        read_timeout_seconds=4,
        detail_delay_seconds=0,
    )
    calls = 0

    def heartbeat() -> bool:
        nonlocal calls
        calls += 1
        return calls < 3

    with pytest.raises(CatalogRetrievalLeaseLost):
        client.retrieve_current_catalog(heartbeat=heartbeat)
