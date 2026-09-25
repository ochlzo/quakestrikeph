"""Requests-backed retrieval and sequential detail enrichment for PHIVOLCS."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import PurePosixPath
from threading import Lock, local
from time import perf_counter
from time import sleep as default_sleep
from typing import Protocol

import requests

from quakestrike.application.phivolcs import CatalogRetrievalError, CatalogRetrievalLeaseLost
from quakestrike.application.reconciliation import persisted_row_values
from quakestrike.domain.source_rows import (
    CatalogEvidence,
    CatalogParseResult,
    DiagnosticCode,
    NormalizedSourceRow,
    SourceDiagnostic,
)
from quakestrike.infrastructure.logging.json_logging import log_event
from quakestrike.infrastructure.phivolcs.parser import (
    MANILA,
    CatalogStructuralError,
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

    def close(self) -> None: ...


class DetailCache(Protocol):
    """Optional short-lived cache for a validated bulletin detail result."""

    def get(self, key: str, signature: str) -> ParsedDetail | None: ...

    def put(self, key: str, signature: str, detail: ParsedDetail) -> None: ...


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
        detail_concurrency: int = 1,
        detail_session_factory: Callable[[], SessionLike] | None = None,
        detail_cache: DetailCache | None = None,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        self._catalog_url = catalog_url
        self._session = session
        self._max_response_bytes = max_response_bytes
        self._timeout = (connect_timeout_seconds, read_timeout_seconds)
        self._detail_delay_seconds = detail_delay_seconds
        if detail_concurrency < 1 or (detail_concurrency > 1 and detail_session_factory is None):
            raise ValueError("Concurrent detail retrieval requires a session factory.")
        self._detail_concurrency = detail_concurrency
        self._detail_session_factory = detail_session_factory
        self._detail_cache = detail_cache
        self._detail_cache_hits = 0
        self._cache_count_lock = Lock()
        self._sleep = sleep

    def retrieve_current_catalog(
        self, *, heartbeat: Callable[[], bool] | None = None
    ) -> CatalogParseResult:
        """Fetch the complete current catalog and enrich its valid rows in order."""

        self._heartbeat(heartbeat)
        started = perf_counter()
        try:
            catalog_body = self._fetch_html(self._catalog_url, heartbeat=heartbeat)
            fetched = perf_counter()
            retrieved_at = datetime.now(UTC)
            parsed = parse_current_catalog(catalog_body, self._catalog_url)
            parsed_at = perf_counter()
        except PhivolcsTransportError as error:
            raise CatalogRetrievalError(error.category) from error
        except CatalogStructuralError as error:
            raise CatalogRetrievalError("catalog_structure") from error
        enriched = self.enrich_rows(parsed.accepted_rows, heartbeat=heartbeat)
        log_event(
            logging.getLogger("data-ingestor"),
            logging.INFO,
            "PHIVOLCS catalog retrieval stages completed.",
            event_code="catalog_retrieval_timing",
            context={
                "catalog_bytes": len(catalog_body),
                "catalog_rows": len(parsed.accepted_rows),
                "detail_urls": len({row.source_url for row in parsed.accepted_rows}),
                "detail_cache_hits": self._detail_cache_hits,
                "catalog_fetch_ms": round((fetched - started) * 1000),
                "catalog_parse_ms": round((parsed_at - fetched) * 1000),
                "detail_enrichment_ms": round((perf_counter() - parsed_at) * 1000),
            },
        )
        return replace(
            parsed,
            accepted_rows=enriched,
            evidence=validated_catalog_evidence(
                parsed, self._catalog_url, catalog_body, retrieved_at
            ),
        )

    def enrich_rows(
        self,
        rows: Iterable[NormalizedSourceRow],
        *,
        heartbeat: Callable[[], bool] | None = None,
    ) -> tuple[NormalizedSourceRow, ...]:
        """Apply the same detail-page enrichment to preserved catalog rows."""

        rows = tuple(rows)
        cache_keys = _catalog_detail_cache_keys(rows)
        if self._detail_concurrency > 1:
            return self._enrich_rows_concurrently(rows, cache_keys, heartbeat=heartbeat)

        details: dict[str, ParsedDetail] = {}
        enriched_rows = []
        fetched_count = 0

        def before_fetch() -> None:
            nonlocal fetched_count
            if fetched_count and self._detail_delay_seconds:
                self._sleep(self._detail_delay_seconds)
            fetched_count += 1

        for row in rows:
            self._heartbeat(heartbeat)
            detail = details.get(row.source_url)
            if detail is None:
                detail = self._cached_detail(
                    row.source_url,
                    cache_keys[row.source_url],
                    heartbeat=heartbeat,
                    before_fetch=before_fetch,
                )
                details[row.source_url] = detail
            enriched_rows.append(
                row.with_detail_enrichment(
                    detail_occurred_at=detail.occurred_at,
                    origin=detail.origin,
                    diagnostics=detail.diagnostics,
                )
            )
        return tuple(enriched_rows)

    def _enrich_rows_concurrently(
        self,
        rows: tuple[NormalizedSourceRow, ...],
        cache_keys: dict[str, tuple[str, str, tuple[datetime, ...]]],
        *,
        heartbeat: Callable[[], bool] | None,
    ) -> tuple[NormalizedSourceRow, ...]:
        """Fetch distinct details with bounded workers, then apply results in row order."""

        urls = tuple(dict.fromkeys(row.source_url for row in rows))
        sessions: list[SessionLike] = []
        thread_state = local()
        session_lock = Lock()
        rate_lock = Lock()
        next_request_at = perf_counter()

        def fetch(url: str) -> ParsedDetail:
            nonlocal next_request_at
            session = getattr(thread_state, "session", None)
            if session is None:
                assert self._detail_session_factory is not None
                session = self._detail_session_factory()
                thread_state.session = session
                with session_lock:
                    sessions.append(session)

            def before_fetch() -> None:
                nonlocal next_request_at
                with rate_lock:
                    pause = max(0.0, next_request_at - perf_counter())
                    if pause:
                        self._sleep(pause)
                    next_request_at = perf_counter() + self._detail_delay_seconds

            return self._cached_detail(
                url, cache_keys[url], session=session, before_fetch=before_fetch
            )

        self._heartbeat(heartbeat)
        try:
            with ThreadPoolExecutor(max_workers=self._detail_concurrency) as executor:
                remaining = iter(urls)
                pending = {
                    executor.submit(fetch, url): url
                    for url in (next(remaining, None) for _ in range(self._detail_concurrency))
                    if url is not None
                }
                details: dict[str, ParsedDetail] = {}
                while pending:
                    self._heartbeat(heartbeat)
                    completed, _ = wait(pending, timeout=5, return_when=FIRST_COMPLETED)
                    for future in completed:
                        details[pending.pop(future)] = future.result()
                        next_url = next(remaining, None)
                        if next_url is not None:
                            pending[executor.submit(fetch, next_url)] = next_url
            return tuple(
                row.with_detail_enrichment(
                    detail_occurred_at=details[row.source_url].occurred_at,
                    origin=details[row.source_url].origin,
                    diagnostics=details[row.source_url].diagnostics,
                )
                for row in rows
            )
        finally:
            for session in sessions:
                session.close()

    def _cached_detail(
        self,
        url: str,
        cache_key: tuple[str, str, tuple[datetime, ...]],
        *,
        heartbeat: Callable[[], bool] | None = None,
        session: SessionLike | None = None,
        before_fetch: Callable[[], None] | None = None,
    ) -> ParsedDetail:
        key, signature, catalog_times = cache_key
        if self._detail_cache is not None:
            cached = self._detail_cache.get(key, signature)
            if cached is not None:
                with self._cache_count_lock:
                    self._detail_cache_hits += 1
                return cached
        if before_fetch is not None:
            before_fetch()
        detail = self._fetch_detail(url, heartbeat=heartbeat, session=session)
        if (
            self._detail_cache is not None
            and detail.occurred_at is not None
            and not detail.diagnostics
            and all(
                _same_catalog_minute(catalog_time, detail.occurred_at)
                for catalog_time in catalog_times
            )
        ):
            self._detail_cache.put(key, signature, detail)
        return detail

    def _fetch_detail(
        self,
        url: str,
        *,
        heartbeat: Callable[[], bool] | None = None,
        session: SessionLike | None = None,
    ) -> ParsedDetail:
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
            return parse_detail_page(self._fetch_html(url, heartbeat=heartbeat, session=session))
        except CatalogRetrievalLeaseLost:
            raise
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

    def _fetch_html(
        self,
        url: str,
        *,
        heartbeat: Callable[[], bool] | None = None,
        session: SessionLike | None = None,
    ) -> bytes:
        response: ResponseLike | None = None
        try:
            response = (session or self._session).get(
                url,
                stream=True,
                timeout=self._timeout,
                allow_redirects=False,
            )
            if 300 <= response.status_code < 400:
                raise PhivolcsTransportError("redirect")
            if response.status_code == 429 or response.status_code >= 500:
                raise PhivolcsTransportError("transient_http")
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
                self._heartbeat(heartbeat)
                if not chunk:
                    continue
                total += len(chunk)
                if total > self._max_response_bytes:
                    raise PhivolcsTransportError("oversized")
                chunks.append(chunk)
            return b"".join(chunks)
        except requests.exceptions.SSLError as error:
            raise PhivolcsTransportError("tls") from error
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as error:
            raise PhivolcsTransportError("request_failed") from error
        except requests.RequestException as error:
            raise PhivolcsTransportError("request_failure") from error
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def _heartbeat(heartbeat: Callable[[], bool] | None) -> None:
        if heartbeat is not None and not heartbeat():
            raise CatalogRetrievalLeaseLost()


def validated_catalog_evidence(
    parsed: CatalogParseResult, source_url: str, body: bytes, retrieved_at: datetime
) -> CatalogEvidence | None:
    """Trust a complete current-month page only when every event row normalized."""

    month = parsed.declared_month_start
    rows = parsed.accepted_rows
    if (
        month is None
        or not rows
        or parsed.candidate_row_count != len(rows)
        or (month.year, month.month)
        != (retrieved_at.astimezone(MANILA).year, retrieved_at.astimezone(MANILA).month)
        or min(row.occurred_at for row in rows).date() != month.date()
        or any(
            (row.occurred_at.year, row.occurred_at.month) != (month.year, month.month)
            for row in rows
        )
        or max(row.occurred_at for row in rows) > retrieved_at
    ):
        return None
    return CatalogEvidence(
        source_url=source_url,
        sha256=sha256(body).hexdigest(),
        retrieved_at=retrieved_at,
        coverage_start=month,
        coverage_end=retrieved_at,
        accepted_rows=len(rows),
    )


def _catalog_detail_cache_keys(
    rows: tuple[NormalizedSourceRow, ...],
) -> dict[str, tuple[str, str, tuple[datetime, ...]]]:
    """Invalidate a cached detail when any catalog row using its URL changes."""

    rows_by_url: dict[str, list[str]] = {}
    times_by_url: dict[str, list[datetime]] = {}
    for row in rows:
        encoded = json.dumps(persisted_row_values(row), sort_keys=True, separators=(",", ":"))
        rows_by_url.setdefault(row.source_url, []).append(encoded)
        times_by_url.setdefault(row.source_url, []).append(row.occurred_at)
    return {
        url: (
            sha256(url.encode()).hexdigest(),
            sha256(json.dumps(sorted(values), separators=(",", ":")).encode()).hexdigest(),
            tuple(times_by_url[url]),
        )
        for url, values in rows_by_url.items()
    }


def _same_catalog_minute(catalog_time: datetime, detail_time: datetime) -> bool:
    local = catalog_time.astimezone(detail_time.tzinfo)
    return (local.date(), local.hour, local.minute) == (
        detail_time.date(),
        detail_time.hour,
        detail_time.minute,
    )
