from datetime import datetime
from zoneinfo import ZoneInfo

from redis.exceptions import ConnectionError

from quakestrike.infrastructure.phivolcs.detail_cache import (
    DETAIL_CACHE_TTL_SECONDS,
    RedisDetailCache,
)
from quakestrike.infrastructure.phivolcs.parser import ParsedDetail


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: list[int] = []
        self.fail = False

    def get(self, name: str) -> str | None:
        if self.fail:
            raise ConnectionError("test outage")
        return self.values.get(name)

    def set(self, name: str, value: str, *, ex: int) -> None:
        self.values[name] = value
        self.expirations.append(ex)

    def delete(self, name: str) -> None:
        self.values.pop(name, None)

    def close(self) -> None:
        pass


def test_detail_cache_expires_successful_result_before_daily_recheck() -> None:
    redis = _Redis()
    cache = RedisDetailCache("redis://unused", client=redis)
    detail = ParsedDetail(
        datetime(2026, 9, 25, 12, 34, 56, tzinfo=ZoneInfo("Asia/Manila")),
        "TECTONIC",
        (),
    )

    cache.put("catalog-key", "original", detail)

    assert cache.get("catalog-key", "original") == detail
    assert cache.get("catalog-key", "changed") is None
    assert cache.get("catalog-key", "original") is None
    assert redis.expirations == [23 * 60 * 60]
    assert DETAIL_CACHE_TTL_SECONDS < 24 * 60 * 60


def test_detail_cache_outage_falls_back_without_repeated_redis_calls() -> None:
    redis = _Redis()
    redis.fail = True
    cache = RedisDetailCache("redis://unused", client=redis)

    assert cache.get("catalog-key", "original") is None
    assert cache.get("catalog-key", "original") is None
