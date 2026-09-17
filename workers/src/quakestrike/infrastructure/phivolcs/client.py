"""Requests-backed retrieval and sequential detail enrichment for PHIVOLCS."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import PurePosixPath
from time import sleep as default_sleep
from typing import Protocol

import requests

from quakestrike.domain.source_rows import CatalogParseResult, DiagnosticCode, SourceDiagnostic
from quakestrike.infrastructure.phivolcs.parser import (
    ParsedDetail,
    parse_current_catalog,
    parse_detail_page,
)


class ResponseLike(Protocol):
    """The small subset of a streamed Requests response used by this adapter."""

    status_code: int
    headers: dict[str, str]

    def iter_content(self, chunk_size: int) -> object: ...

    def close(self) -> None: ...


class SessionLike(Protocol):
    """The small subset of a Requests session used by this adapter."""

    def get(self, url: str, **kwargs: object) -> ResponseLike: ...


class PhivolcsTransportError(RuntimeError):
    """A catalog-level transport failure that stops this retrieval attempt."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class PhivolcsCatalogClient:
    """Retrieve one current catalog and enrich each distinct visible bulletin URL."""

    def __init__(
        self,
        *,
        catalog_url: str,
        session: SessionLike,
        max_response_bytes: int,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        detail_delay_seconds: float,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        self._catalog_url = catalog_url
        self._session = session
        self._max_response_bytes = max_response_bytes
        self._timeout = (connect_timeout_seconds, read_timeout_seconds)
        self._detail_delay_seconds = detail_delay_seconds
        self._sleep = sleep

    def retrieve_current_catalog(self) -> CatalogParseResult:
        """Fetch the complete current catalog and enrich its valid rows in order."""

        catalog_body = self._fetch_html(self._catalog_url)
        parsed = parse_current_catalog(catalog_body, self._catalog_url)
        details: dict[str, ParsedDetail] = {}
        enriched_rows = []
        for row in parsed.accepted_rows:
            detail = details.get(row.source_url)
            if detail is None:
                if details and self._detail_delay_seconds:
                    self._sleep(self._detail_delay_seconds)
                detail = self._fetch_detail(row.source_url)
                details[row.source_url] = detail
            enriched_rows.append(
                row.with_detail_enrichment(
                    detail_occurred_at=detail.occurred_at,
                    origin=detail.origin,
                    diagnostics=detail.diagnostics,
                )
            )
        return replace(parsed, accepted_rows=tuple(enriched_rows))

    def _fetch_detail(self, url: str) -> ParsedDetail:
        suffix = PurePosixPath(url).suffix.casefold()
        if suffix in {".pdf", ".jpg", ".jpeg"}:
            return ParsedDetail(
                None,
                None,
                (
                    SourceDiagnostic(
                        DiagnosticCode.DETAIL_NON_HTML_RESPONSE, {"asset_type": suffix[1:]}
                    ),
                ),
            )
        try:
            return parse_detail_page(self._fetch_html(url))
        except PhivolcsTransportError as error:
            code = (
                DiagnosticCode.DETAIL_NON_HTML_RESPONSE
                if error.category == "non_html"
                else DiagnosticCode.DETAIL_FETCH_FAILED
            )
            return ParsedDetail(
                None,
                None,
                (SourceDiagnostic(code),),
            )

    def _fetch_html(self, url: str) -> bytes:
        response: ResponseLike | None = None
        try:
            response = self._session.get(
                url,
                stream=True,
                timeout=self._timeout,
                allow_redirects=False,
            )
            if 300 <= response.status_code < 400:
                raise PhivolcsTransportError("redirect")
            if response.status_code >= 400:
                raise PhivolcsTransportError("http_status")
            content_type = (
                response.headers.get("Content-Type", "").split(";", 1)[0].strip().casefold()
            )
            if content_type not in {"text/html", "application/xhtml+xml"}:
                raise PhivolcsTransportError("non_html")
            declared_length = response.headers.get("Content-Length")
            if (
                declared_length is not None
                and declared_length.isdecimal()
                and int(declared_length) > self._max_response_bytes
            ):
                raise PhivolcsTransportError("oversized")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=8192):  # type: ignore[union-attr]
                if not chunk:
                    continue
                total += len(chunk)
                if total > self._max_response_bytes:
                    raise PhivolcsTransportError("oversized")
                chunks.append(chunk)
            return b"".join(chunks)
        except requests.RequestException as error:
            raise PhivolcsTransportError("request_failed") from error
        finally:
            if response is not None:
                response.close()
