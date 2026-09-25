"""Best-effort, short-lived cache of successfully parsed PHIVOLCS detail pages."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Protocol

from redis import Redis
from redis.exceptions import RedisError

from quakestrike.infrastructure.logging.json_logging import log_event
from quakestrike.infrastructure.phivolcs.parser import ParsedDetail

DETAIL_CACHE_TTL_SECONDS = 23 * 60 * 60
_KEY_PREFIX = "quakestrike:phivolcs-detail:v1:"
_ORIGINS = {None, "TECTONIC", "VOLCANIC", "TECTONIC-VOLCANIC"}


class CacheClient(Protocol):
    def get(self, name: str) -> bytes | str | None: ...

    def set(self, name: str, value: str, *, ex: int) -> object: ...

    def delete(self, name: str) -> object: ...

    def close(self) -> None: ...


class RedisDetailCache:
    """A cache miss or Redis failure leaves the source fetch as the safe fallback."""

    def __init__(self, redis_url: str, *, client: CacheClient | None = None) -> None:
        self._client = client or Redis.from_url(
            redis_url, socket_timeout=0.5, socket_connect_timeout=0.5
        )
        self._disabled = False

    def get(self, key: str, signature: str) -> ParsedDetail | None:
        if self._disabled:
            return None
        try:
            raw = self._client.get(_KEY_PREFIX + key)
        except RedisError:
            self._disable()
            return None
        if raw is None:
            return None
        try:
            value = json.loads(raw)
            if value["catalog_signature"] != signature:
                self._client.delete(_KEY_PREFIX + key)
                return None
            occurred_at = datetime.fromisoformat(value["occurred_at"])
            origin = value["origin"]
            if occurred_at.utcoffset() is None or origin not in _ORIGINS:
                return None
            return ParsedDetail(occurred_at, origin, ())
        except RedisError:
            self._disable()
            return None
        except (KeyError, TypeError, ValueError):
            return None

    def put(self, key: str, signature: str, detail: ParsedDetail) -> None:
        if self._disabled or detail.occurred_at is None or detail.diagnostics:
            return
        value = json.dumps(
            {
                "catalog_signature": signature,
                "occurred_at": detail.occurred_at.isoformat(),
                "origin": detail.origin,
            },
            separators=(",", ":"),
        )
        try:
            self._client.set(_KEY_PREFIX + key, value, ex=DETAIL_CACHE_TTL_SECONDS)
        except RedisError:
            self._disable()

    def close(self) -> None:
        try:
            self._client.close()
        except RedisError:
            pass

    def _disable(self) -> None:
        if not self._disabled:
            self._disabled = True
            log_event(
                logging.getLogger("data-ingestor"),
                logging.WARNING,
                "Detail cache is unavailable; source retrieval continues.",
                event_code="detail_cache_unavailable",
            )
