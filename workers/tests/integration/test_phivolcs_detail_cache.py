"""The cache survives separate ingestion deliveries through isolated Redis."""

import os
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from redis import Redis

from quakestrike.infrastructure.phivolcs.detail_cache import RedisDetailCache
from quakestrike.infrastructure.phivolcs.parser import ParsedDetail

pytestmark = pytest.mark.integration


def test_detail_result_is_reused_across_cache_clients() -> None:
    redis_url = os.environ.get("TEST_REDIS_URL")
    if redis_url is None:
        pytest.skip("TEST_REDIS_URL is required for Redis integration tests.")
    key = uuid4().hex
    detail = ParsedDetail(
        datetime(2026, 9, 25, 12, 34, 56, tzinfo=ZoneInfo("Asia/Manila")),
        "VOLCANIC",
        (),
    )
    writer = RedisDetailCache(redis_url)
    reader = RedisDetailCache(redis_url)
    cleanup = Redis.from_url(redis_url)
    try:
        writer.put(key, "original", detail)
        assert reader.get(key, "original") == detail
        assert reader.get(key, "changed") is None
        assert reader.get(key, "original") is None
    finally:
        cleanup.delete("quakestrike:phivolcs-detail:v1:" + key)
        writer.close()
        reader.close()
        cleanup.close()
