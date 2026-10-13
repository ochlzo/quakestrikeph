from uuid import uuid4

from redis import Redis
from redis.exceptions import RedisError

from quakestrike.alert_testing.domain.sessions import (
    CONTROL_RETENTION_MS,
    SESSION_LIFETIME_MS,
    Session,
    SessionConflict,
)

PREFIX = "quakestrike:alert-testing:"
CONTROL_KEY = PREFIX + "session"
CLEANUP_LEASE_MS = 10_000

# Redis time and one script make session gates independent of process clocks.
SESSION_SCRIPT = """
local key = KEYS[1]
local operation = ARGV[1]
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local id = redis.call('HGET', key, 'session_id')
if id and redis.call('HGET', key, 'lifecycle') == 'active'
    and tonumber(redis.call('HGET', key, 'expires_at_ms')) <= now then
    redis.call('HSET', key, 'lifecycle', 'expired', 'cleanup', 'pending',
        'closed_at_ms', tostring(now))
end
local function view()
    local result = redis.call('HGETALL', key)
    table.insert(result, 'server_time_ms')
    table.insert(result, tostring(now))
    return result
end
if operation == 'start' then
    if id and redis.call('HGET', key, 'lifecycle') == 'active' then
        return view()
    end
    if id and redis.call('HGET', key, 'cleanup') ~= 'complete' then
        return {'conflict'}
    end
    local deadline = now + tonumber(ARGV[3])
    redis.call('DEL', key)
    redis.call('HSET', key, 'session_id', ARGV[2], 'started_at_ms', tostring(now),
        'expires_at_ms', tostring(deadline), 'lifecycle', 'active', 'cleanup', 'none',
        'cursor', '0')
    redis.call('PEXPIREAT', key, deadline + tonumber(ARGV[4]))
    return view()
end
if not id then return {} end
if operation == 'read' then return view() end
if id ~= ARGV[2] then return {'conflict'} end
if operation == 'owned' then return view() end
if operation == 'close' then
    if redis.call('HGET', key, 'lifecycle') == 'active' then
        redis.call('HSET', key, 'lifecycle', 'closed', 'cleanup', 'pending',
            'closed_at_ms', tostring(now))
    end
    return view()
end
if redis.call('HGET', key, 'lifecycle') == 'active' then return {'conflict'} end
if operation == 'claim' then
    if redis.call('HGET', key, 'cleanup') == 'complete' then return {'complete'} end
    if tonumber(redis.call('HGET', key, 'calls_until_ms') or '0') > now then
        return {'busy'}
    end
    if tonumber(redis.call('HGET', key, 'lease_until_ms') or '0') > now then
        return {'busy'}
    end
    redis.call('HSET', key, 'cleanup', 'running', 'cleanup_token', ARGV[3],
        'lease_until_ms', tostring(now + tonumber(ARGV[4])))
    return {'claimed', redis.call('HGET', key, 'cursor') or '0'}
end
if redis.call('HGET', key, 'cleanup_token') ~= ARGV[3] then return view() end
if operation == 'finish' then
    redis.call('HSET', key, 'cursor', ARGV[4], 'cleanup',
        ARGV[4] == '0' and 'complete' or 'pending')
    if ARGV[4] == '0' then redis.call('HSET', key, 'cleanup_completed_at_ms', tostring(now)) end
elseif operation == 'fail' then
    redis.call('HSET', key, 'cleanup', 'failed')
end
redis.call('HDEL', key, 'cleanup_token', 'lease_until_ms')
return view()
"""


class RedisSessionStore:
    def __init__(self, client: Redis):
        self.client = client
        self.script = client.register_script(SESSION_SCRIPT)

    def _execute(self, *args: str | int) -> list[str]:
        result = self.script(keys=[CONTROL_KEY], args=list(args))
        if result == ["conflict"]:
            raise SessionConflict
        return result

    @staticmethod
    def _session(values: list[str]) -> Session:
        if not values:
            raise SessionConflict
        fields = dict(zip(values[::2], values[1::2], strict=True))
        return Session(
            session_id=fields["session_id"],
            started_at_ms=int(fields["started_at_ms"]),
            expires_at_ms=int(fields["expires_at_ms"]),
            lifecycle=fields["lifecycle"],
            cleanup=fields["cleanup"],
            server_time_ms=int(fields["server_time_ms"]),
            calls_until_ms=int(fields.get("calls_until_ms", "0")),
            closed_at_ms=int(fields.get("closed_at_ms", "0")),
            cleanup_completed_at_ms=int(fields.get("cleanup_completed_at_ms", "0")),
        )

    def read(self) -> Session | None:
        values = self._execute("read")
        return self._session(values) if values else None

    def start(self) -> Session:
        return self._session(
            self._execute("start", str(uuid4()), SESSION_LIFETIME_MS, CONTROL_RETENTION_MS)
        )

    def close(self, session_id: str) -> Session:
        return self._session(self._execute("close", session_id))

    def cleanup(self, session_id: str) -> Session:
        token = str(uuid4())
        claim = self._execute("claim", session_id, token, CLEANUP_LEASE_MS)
        if claim in (["complete"], ["busy"]):
            return self._session(self._execute("owned", session_id))
        if not claim:
            raise SessionConflict
        cursor = int(claim[1])
        try:
            # Bound each request; closed sessions accept no new child records.
            for _ in range(10):
                cursor, keys = self.client.scan(cursor, match=f"{PREFIX}{session_id}:*", count=100)
                if keys:
                    self.client.unlink(*keys)
                if cursor == 0:
                    break
        except RedisError:
            return self._session(self._execute("fail", session_id, token))
        return self._session(self._execute("finish", session_id, token, cursor))
