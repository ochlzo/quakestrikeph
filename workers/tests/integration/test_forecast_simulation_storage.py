import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import new as hmac_new
from ipaddress import ip_address
from uuid import uuid4

import pytest
from redis import Redis
from sqlalchemy import insert

from quakestrike.domain.features import HISTORY_WINDOW, HistoryCoverage
from quakestrike.forecast_simulation.catalog import BootstrapCoverage, SimulationCatalog
from quakestrike.forecast_simulation.quota import SimulationQuota
from quakestrike.infrastructure.database.tables import (
    earthquake_event_revisions,
    earthquake_events,
    ingestion_runs,
    source_catalog_evidence,
)


def test_catalog_uses_successful_coverage_and_latest_revisions(migrated_engine):
    cutoff = datetime(2026, 11, 19, tzinfo=UTC)
    bootstrap_id, successful_run, failed_run = uuid4(), uuid4(), uuid4()
    split = cutoff - timedelta(days=4)
    bootstrap = BootstrapCoverage(
        bootstrap_id, "a" * 64, None, HistoryCoverage(cutoff - HISTORY_WINDOW, split, True)
    )
    with migrated_engine.begin() as connection:
        for run, kind, status, snapshot_hash in (
            (bootstrap_id, "backfill", "succeeded", bootstrap.snapshot_hash),
            (successful_run, "scheduled", "succeeded", None),
            (failed_run, "scheduled", "failed", None),
        ):
            connection.execute(
                insert(ingestion_runs).values(
                    run_id=run,
                    trigger_type=kind,
                    status=status,
                    started_at=split,
                    finished_at=cutoff,
                    correlation_id=uuid4(),
                    bootstrap_snapshot_sha256=snapshot_hash,
                )
            )
        for run, end in ((successful_run, cutoff), (failed_run, cutoff + timedelta(hours=1))):
            connection.execute(
                insert(source_catalog_evidence).values(
                    run_id=run,
                    source_url="https://example.org/catalog",
                    catalog_sha256="b" * 64,
                    retrieved_at=end,
                    coverage_start=split,
                    coverage_end=end,
                    accepted_rows=1,
                )
            )
        for index, event_time in enumerate(
            (cutoff - timedelta(hours=1), cutoff, cutoff - timedelta(days=2))
        ):
            event = uuid4()
            connection.execute(
                insert(earthquake_events).values(
                    event_id=event,
                    first_seen_run_id=successful_run,
                    last_seen_run_id=successful_run,
                )
            )
            for revision in range(1, 3 if index == 2 else 2):
                connection.execute(
                    insert(earthquake_event_revisions).values(
                        event_revision_id=uuid4(),
                        event_id=event,
                        revision_number=revision,
                        ingestion_run_id=successful_run,
                        source_event_group_id=f"SIMULATION_TEST_{index}",
                        source_url="https://example.org/catalog",
                        source_time_precision="second",
                        event_time=event_time,
                        latitude=14,
                        longitude=121,
                        depth_km=12,
                        magnitude=2 if revision == 1 else 0.8,
                        location_description="Sanitized event",
                    )
                )
    scenario = {"latitude": 14.0, "longitude": 121.0, "magnitude": 5.2, "depthKm": 18.0}
    now = cutoff + timedelta(hours=2)
    assert SimulationCatalog(migrated_engine, None).read(now)[0].status == "insufficient_history"
    status, features = SimulationCatalog(migrated_engine, bootstrap).read(now, scenario)
    assert status.cutoff == cutoff
    assert features["catalog_m1_plus_count_past_7d"] == 1
    assert features["local_m1_plus_count_past_24h_within_50km"] == 1


def test_atomic_rolling_quota_uses_both_limits_and_the_later_deadline():
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL is required for Redis integration tests.")
    ip = "192.0.2.55"
    secret = uuid4().bytes
    guests = [str(uuid4()) for _ in range(116)]
    guest_key = f"forecast-simulation:guest:{guests[0]}"
    ip_key = f"forecast-simulation:ip:{hmac_new(secret, ip_address(ip).packed, sha256).hexdigest()}"
    with Redis.from_url(url) as redis:
        quota = SimulationQuota(redis, secret)
        try:
            with ThreadPoolExecutor(12) as executor:
                attempts = list(executor.map(lambda _: quota.admit(guests[0], ip), range(24)))
            assert attempts.count(None) == 5
            assert redis.zcard(ip_key) == 5
            for guest in guests[1:]:
                assert quota.admit(guest, ip) is None
            assert redis.zcard(ip_key) == 120

            oldest_guest, guest_time = redis.zrange(guest_key, 0, 0, withscores=True)[0]
            redis.zadd(guest_key, {oldest_guest: guest_time - 10_000})
            ip_time = redis.zrange(ip_key, 0, 0, withscores=True)[0][1]
            retry_at, _ = quota.admit(guests[0], ip)
            assert retry_at == datetime.fromtimestamp((ip_time + 600_000) / 1000, UTC)
            assert redis.zcard(guest_key) == 5
            assert redis.zcard(ip_key) == 120
            for member, score in redis.zrange(ip_key, 0, -1, withscores=True):
                redis.zadd(ip_key, {member: score - 600_000})
            assert quota.admit(guests[1], f"::ffff:{ip}") is None
            assert redis.zcard(ip_key) == 1
        finally:
            redis.delete(ip_key, *(f"forecast-simulation:guest:{guest}" for guest in guests))
