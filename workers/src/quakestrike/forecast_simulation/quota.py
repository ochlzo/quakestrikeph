"""Atomically admit a simulation start against both rolling Redis quotas."""

from datetime import UTC, datetime
from hashlib import sha256
from hmac import new as hmac_new
from ipaddress import IPv6Address, ip_address
from uuid import uuid4

from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

_ADMIT = """
local clock = redis.call('TIME')
local now = clock[1] * 1000 + math.floor(clock[2] / 1000)
local window = 600000
local limits = {5, 120}
local retry = 0
for i, key in ipairs(KEYS) do
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
    local count = redis.call('ZCARD', key)
    if count >= limits[i] then
        local oldest = redis.call('ZRANGE', key, count - limits[i], count - limits[i], 'WITHSCORES')
        retry = math.max(retry, tonumber(oldest[2]) + window)
    end
end
if retry > 0 then
    return {retry, math.ceil((retry - now) / 1000)}
end
for _, key in ipairs(KEYS) do
    redis.call('ZADD', key, now, ARGV[1])
    redis.call('PEXPIRE', key, window)
end
return {0, 0}
"""


class QuotaUnavailable(Exception):
    """The quota store rejected the request before admission."""


class QuotaOutcomeUnknown(Exception):
    """The connection failed after dispatching the atomic admission."""


class SimulationQuota:
    def __init__(self, redis: Redis, key: bytes) -> None:
        self.redis = redis
        self.key = key

    def admit(self, guest_id: str, client_ip: str) -> tuple[datetime, int] | None:
        address = ip_address(client_ip)
        if isinstance(address, IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        ip_hash = hmac_new(self.key, address.packed, sha256).hexdigest()
        try:
            with self.redis.client() as connection:
                connection.ping()
                try:
                    retry, seconds = connection.eval(
                        _ADMIT,
                        2,
                        f"forecast-simulation:guest:{guest_id}",
                        f"forecast-simulation:ip:{ip_hash}",
                        str(uuid4()),
                    )
                except (RedisConnectionError, RedisTimeoutError) as error:
                    raise QuotaOutcomeUnknown from error
        except RedisError as error:
            raise QuotaUnavailable from error
        return (datetime.fromtimestamp(retry / 1000, UTC), seconds) if retry else None
