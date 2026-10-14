import json

from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.infrastructure.deliveries import GATE
from quakestrike.alert_testing.infrastructure.preparation import encode
from quakestrike.alert_testing.infrastructure.redis import CONTROL_KEY, PREFIX

READ = (
    GATE
    + """
return redis.call('GET', KEYS[2]) or ''
"""
)
SAVE = (
    GATE
    + """
local previous = redis.call('GET', KEYS[2])
local revision = previous and cjson.decode(previous).revision or 0
if previous == ARGV[3] then return {'saved'} end
if revision ~= tonumber(ARGV[2]) then return {'stale'} end
if ARGV[4] ~= '' then
 local preview = cjson.decode(ARGV[4])
 if preview.scenario.forecast.window_end_ms <= now then return {'invalid'} end
 local existing = redis.call('GET', KEYS[3])
 if existing and cjson.decode(existing).scenario.preparation_token ~=
  preview.scenario.preparation_token then return {'invalid'} end
 redis.call('SET', KEYS[3], ARGV[4], 'PXAT', deadline, 'NX')
end
redis.call('SET', KEYS[2], ARGV[3], 'PXAT', deadline)
return {'saved'}
"""
)


class RedisWorkspaceStore:
    def __init__(self, client, public_url):
        self.client, self.public_url = client, public_url
        self.reader = client.register_script(READ)
        self.writer = client.register_script(SAVE)

    def _key(self, owner, suffix):
        return f"{PREFIX}{owner}:{suffix}"

    def read(self, owner, workspace):
        raw = self.reader(
            keys=[CONTROL_KEY, self._key(owner, f"workspace:{workspace}")], args=[owner]
        )
        if raw == ["conflict"]:
            raise SessionConflict
        return json.loads(raw) if raw else {"revision": 0, "missing": True}

    def save(self, owner, workspace, revision, draft, preview):
        event = preview["scenario"]["event_id"] if preview else None
        record = {
            "revision": revision + 1,
            **draft,
            "preview_url": f"{self.public_url}/forecasts/{event}?test=true" if event else None,
        }
        result = self.writer(
            keys=[
                CONTROL_KEY,
                self._key(owner, f"workspace:{workspace}"),
                self._key(owner, f"preview:{event}"),
            ],
            args=[owner, revision, encode(record), encode(preview) if preview else ""],
        )
        if result == ["conflict"]:
            raise SessionConflict
        if result != ["saved"]:
            raise ValueError("Workspace changed or preview expired. Reload before retrying.")
        return {"revision": revision + 1, "preview_url": record["preview_url"]}
