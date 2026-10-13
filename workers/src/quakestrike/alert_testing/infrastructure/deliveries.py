"""Session-gated persistence, isolated Stream recovery, and attempt fencing."""

import hashlib
import json

from quakestrike.alert_testing.application.submissions import submitted_record
from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.infrastructure.preparation import encode
from quakestrike.alert_testing.infrastructure.redis import CONTROL_KEY, PREFIX

GROUP = "test-delivery-v1"
CALL_RESERVATION_MS = 15_000
RECOVERY_IDLE_MS = 30_000

GATE = """
local clock = redis.call('TIME')
local now = tonumber(clock[1])*1000 + math.floor(tonumber(clock[2])/1000)
local deadline = tonumber(redis.call('HGET', KEYS[1], 'expires_at_ms') or '0')
if redis.call('HGET', KEYS[1], 'session_id') ~= ARGV[1]
 or redis.call('HGET', KEYS[1], 'lifecycle') ~= 'active' or now >= deadline then
 return {'conflict'}
end
"""

SUBMIT = (
    GATE
    + """
local existing = redis.call('GET', KEYS[3])
if existing then
 if cjson.decode(existing).fingerprint ~= ARGV[3] then return {'invalid'} end
end
if not existing and tonumber(ARGV[4]) <= now then return {'expired'} end
if not existing and redis.call('EXISTS', KEYS[2]) == 1 then return {'invalid'} end
for i = 4, 5 do
 local kind = redis.call('TYPE', KEYS[i]).ok
 if kind ~= 'none' and kind ~= 'zset' then return {'invalid'} end
end
local job = cjson.decode(existing or ARGV[6])
redis.call('SET', KEYS[3], existing or ARGV[6], 'PXAT', deadline, 'NX')
redis.call('SET', KEYS[2], job.public_record, 'PXAT', deadline, 'NX')
local submitted = cjson.decode(job.public_record).submitted_at_ms
redis.call('ZADD', KEYS[4], submitted, ARGV[2])
redis.call('PEXPIREAT', KEYS[4], deadline)
if job.queue_status == 'pending' then
 redis.call('ZADD', KEYS[5], submitted, ARGV[2])
 redis.call('PEXPIREAT', KEYS[5], deadline)
end
return {existing and 'existing' or 'created'}
"""
)

PUBLISH = (
    GATE
    + """
local raw = redis.call('GET', KEYS[2])
if not raw then return {'missing'} end
local job = cjson.decode(raw)
if job.queue_status == 'enqueued' then
 redis.call('ZREM', KEYS[4], ARGV[2])
 return {'enqueued'}
end
if redis.call('EXISTS', KEYS[5]) == 0 then return {'pending'} end
local kind = redis.call('TYPE', KEYS[3]).ok
if kind ~= 'none' and kind ~= 'stream' then return {'pending'} end
if kind == 'none' then
 redis.call('XGROUP', 'CREATE', KEYS[3], ARGV[3], '0', 'MKSTREAM')
 redis.call('PEXPIREAT', KEYS[3], deadline)
end
redis.call('XADD', KEYS[3], '*', 'message_version', '1',
 'session_id', ARGV[1], 'event_id', ARGV[2], 'job_id', job.job_id)
job.queue_status = 'enqueued'
redis.call('SET', KEYS[2], cjson.encode(job), 'PXAT', deadline)
redis.call('ZREM', KEYS[4], ARGV[2])
return {'enqueued'}
"""
)

READ = (
    GATE
    + """
local result = {}
for i = 2, #KEYS do table.insert(result, redis.call('GET', KEYS[i]) or '') end
return result
"""
)

FREEZE = (
    GATE
    + """
local raw = redis.call('GET', KEYS[2])
if not raw then return {'missing'} end
local job = cjson.decode(raw)
if not job.content then
 job.content = cjson.decode(ARGV[2])
 redis.call('SET', KEYS[2], cjson.encode(job), 'PXAT', deadline)
end
return {cjson.encode(job)}
"""
)

BEGIN = (
    GATE
    + """
if redis.call('EXISTS', KEYS[2]) == 0 then return {'missing'} end
local job = cjson.decode(redis.call('GET', KEYS[2]))
local selected = false
for _, id in ipairs(job.selected) do if id == ARGV[2] then selected = true end end
if not selected then return {'invalid'} end
if ARGV[5] == 'call' and job.window_end_ms <= now then return {'expired'} end
if redis.call('HEXISTS', KEYS[3], ARGV[3]) == 1 then return {'existing'} end
local row = cjson.decode(ARGV[4])
row.reserved_until_ms = now + tonumber(ARGV[6])
redis.call('HSET', KEYS[3], ARGV[3], cjson.encode(row))
redis.call('PEXPIREAT', KEYS[3], deadline)
if ARGV[5] == 'call' then
 redis.call('HSET', KEYS[4], row.token, ARGV[3])
 redis.call('PEXPIREAT', KEYS[4], deadline)
 local untilMs = now + tonumber(ARGV[6])
 redis.call('HSET', KEYS[1], 'calls_until_ms', tostring(math.max(untilMs,
  tonumber(redis.call('HGET', KEYS[1], 'calls_until_ms') or '0'))))
end
return {'reserved'}
"""
)

ALLOW = (
    GATE
    + """
local scenario = redis.call('GET', KEYS[3])
if not scenario then return {'missing'} end
if cjson.decode(scenario).scenario.forecast.window_end_ms <= now then return {'expired'} end
local raw = redis.call('HGET', KEYS[2], ARGV[2])
if not raw then return {'missing'} end
local row = cjson.decode(raw)
if row.token ~= ARGV[3] or row.status ~= 'unknown'
 or now + 12000 > row.reserved_until_ms then return {'stale'} end
return {'allowed'}
"""
)

FINISH = (
    GATE
    + """
local raw = redis.call('HGET', KEYS[2], ARGV[2])
if not raw then return {'missing'} end
local row = cjson.decode(raw)
if row.token ~= ARGV[3] then return {'stale'} end
local submitted = cjson.decode(ARGV[4])
local reference = submitted.provider_reference
local identity = ARGV[5] .. ':' .. row.token
if reference and reference ~= cjson.null then
 local mapped = redis.call('HGET', KEYS[3], row.channel .. ':' .. reference)
 if (row.provider_reference and row.provider_reference ~= cjson.null
  and row.provider_reference ~= reference)
  or (mapped and mapped ~= identity) then
  row.evidence_note = 'Provider reference conflict; reconciliation requires investigation.'
  redis.call('HSET', KEYS[2], ARGV[2], cjson.encode(row))
  return {'reference-conflict'}
 end
 redis.call('HSET', KEYS[3], row.channel .. ':' .. reference, identity)
 redis.call('PEXPIREAT', KEYS[3], deadline)
 row.provider_reference = reference
end
row.submission_status = submitted.status
row.provider_evidence = submitted.provider_evidence
if not row.provider_status_at_ms and not row.delivery_evidence then
 row.status = submitted.status
 row.reason = submitted.reason
 row.error_code = submitted.error_code
end
if row.channel == 'sms' and row.provider_reference and row.provider_reference ~= cjson.null
 and (row.status == 'accepted' or row.status == 'unknown') then
 redis.call('ZADD', KEYS[4], now, ARGV[5] .. ':' .. ARGV[2])
 redis.call('PEXPIREAT', KEYS[4], deadline)
end
redis.call('HSET', KEYS[2], ARGV[2], cjson.encode(row))
return {'finished'}
"""
)

CONSUME = (
    GATE
    + """
if redis.call('TYPE', KEYS[2]).ok ~= 'stream' then return {} end
local recovered = redis.call('XAUTOCLAIM', KEYS[2], ARGV[2], ARGV[3], ARGV[4], '0-0',
 'COUNT', 1)
if #recovered[2] > 0 then return recovered[2] end
local fresh = redis.call('XREADGROUP', 'GROUP', ARGV[2], ARGV[3], 'COUNT', 1,
 'STREAMS', KEYS[2], '>')
if not fresh then return {} end
return fresh[1][2]
"""
)

ROWS = GATE + "return redis.call('HVALS', KEYS[2])"
HISTORY = (
    GATE
    + """
local total = redis.call('ZCARD', KEYS[2])
local pages = math.max(1, math.ceil(total / 50))
local page = math.min(tonumber(ARGV[2]), pages)
return {tostring(page), tostring(pages), redis.call('ZREVRANGE', KEYS[2],
 (page - 1) * 50, page * 50 - 1)}
"""
)
OUTBOX = GATE + "return redis.call('ZRANGE', KEYS[2], 0, 49)"

# Each sweep claims one known reference and postpones its next poll before transport.
POLL = (
    GATE
    + """
local entries = redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', now, 'LIMIT', 0, 1)
if #entries == 0 then return {} end
local member = entries[1]
local event, slot = string.match(member, '^([^:]+):(.+)$')
local key = ARGV[2] .. 'recipients:' .. event
local raw = redis.call('HGET', key, slot)
if not raw then redis.call('ZREM', KEYS[2], member) return {} end
local row = cjson.decode(raw)
if row.channel ~= 'sms' or (row.status ~= 'accepted' and row.status ~= 'unknown')
 or not row.provider_reference or row.provider_reference == cjson.null then
 redis.call('ZREM', KEYS[2], member) return {}
end
redis.call('ZADD', KEYS[2], now + 60000, member)
redis.call('HSET', KEYS[1], 'calls_until_ms', tostring(math.max(now + 15000,
 tonumber(redis.call('HGET', KEYS[1], 'calls_until_ms') or '0'))))
return {event, raw}
"""
)

RECONCILE_SMS = (
    GATE
    + """
local raw = redis.call('HGET', KEYS[2], ARGV[2])
if not raw then return {'missing'} end
local row = cjson.decode(raw)
if row.token ~= ARGV[3] or row.channel ~= 'sms' or row.provider_reference ~= ARGV[4]
 or redis.call('HGET', KEYS[3], 'sms:' .. ARGV[4]) ~= ARGV[5] .. ':' .. row.token then
 return {'reference-conflict'}
end
local status = ARGV[6]
local rank = {unknown=0, accepted=1, failed=2, delivered=3}
if row.status == 'delivered' or rank[row.status] >= rank[status] then return {'ignored'} end
row.status = status
row.delivery_evidence = true
row.error_code = ARGV[7] ~= '' and ARGV[7] or cjson.null
row.provider_evidence = cjson.decode(ARGV[8])
row.reason = status == 'delivered' and 'Provider confirmed delivery.'
 or status == 'failed' and 'Provider reported delivery failure.'
 or 'Provider accepted the request; delivery is not confirmed.'
redis.call('HSET', KEYS[2], ARGV[2], cjson.encode(row))
if status == 'delivered' or status == 'failed' then
 redis.call('ZREM', KEYS[4], ARGV[5] .. ':' .. ARGV[2])
end
return {'applied'}
"""
)


class RedisDeliveryStore:
    def __init__(self, client, public_base_url):
        self.client, self.public_base_url = client, public_base_url
        self.scripts = {
            name: client.register_script(script)
            for name, script in {
                "submit": SUBMIT,
                "publish": PUBLISH,
                "read": READ,
                "freeze": FREEZE,
                "begin": BEGIN,
                "allow": ALLOW,
                "finish": FINISH,
                "consume": CONSUME,
                "rows": ROWS,
                "history": HISTORY,
                "outbox": OUTBOX,
                "poll": POLL,
                "reconcile_sms": RECONCILE_SMS,
            }.items()
        }

    def key(self, owner, suffix):
        return f"{PREFIX}{owner}:{suffix}"

    def execute(self, operation, owner, suffixes, *args):
        result = self.scripts[operation](
            keys=[CONTROL_KEY, *(self.key(owner, suffix) for suffix in suffixes)],
            args=[owner, *args],
        )
        if result == ["conflict"]:
            raise SessionConflict
        return result

    def submit(self, owner, event, scenario, inputs, selected):
        clock = self.client.time()
        now = clock[0] * 1000 + clock[1] // 1000
        record = submitted_record(scenario, now)
        fingerprint = hashlib.sha256(
            encode([scenario, inputs, sorted(selected)]).encode()
        ).hexdigest()
        job = {
            "job_id": event,
            "event_id": event,
            "fingerprint": fingerprint,
            "selected": selected,
            "queue_status": "pending",
            "public_record": json.dumps(record, allow_nan=False),
            "window_end_ms": scenario["forecast"]["window_end_ms"],
            "forecast_url": f"{self.public_base_url}/forecasts/{event}?test=true",
        }
        response = self.execute(
            "submit",
            owner,
            [f"scenario:{event}", f"job:{event}", "history", "outbox"],
            event,
            fingerprint,
            job["window_end_ms"],
            json.dumps(record, allow_nan=False),
            json.dumps(job),
        )
        if response in (["invalid"], ["expired"]):
            raise ValueError("Invalid or expired submission.")
        self.publish(owner, event)
        return self.results(owner, event)

    def publish(self, owner, event):
        return self.execute(
            "publish", owner, [f"job:{event}", "queue", "outbox", f"scenario:{event}"], event, GROUP
        )

    def load(self, owner, event):
        raw = self.execute("read", owner, [f"scenario:{event}", f"job:{event}"])
        return (json.loads(raw[0]), json.loads(raw[1])) if all(raw) else (None, None)

    def freeze(self, owner, event, content):
        raw = self.execute("freeze", owner, [f"job:{event}"], json.dumps(content))
        return json.loads(raw[0]) if raw != ["missing"] else None

    def begin(self, owner, event, user, channel, row, call=False):
        row = {**row, "user_id": user, "channel": channel}
        result = self.execute(
            "begin",
            owner,
            [f"job:{event}", f"recipients:{event}", f"attempts:{event}"],
            user,
            f"{user}:{channel}",
            json.dumps(row),
            "call" if call else "skip",
            CALL_RESERVATION_MS,
        )
        return result == ["reserved"]

    def finish(self, owner, event, row):
        return self.execute(
            "finish",
            owner,
            [f"recipients:{event}", "references", "sms-polls"],
            f"{row['user_id']}:{row['channel']}",
            row["token"],
            json.dumps(row),
            event,
        )

    def allow(self, owner, event, row):
        return self.execute(
            "allow",
            owner,
            [f"recipients:{event}", f"scenario:{event}"],
            f"{row['user_id']}:{row['channel']}",
            row["token"],
        ) == ["allowed"]

    def history(self, owner, page=1):
        page, pages, events = self.execute("history", owner, ["history"], page)
        return {
            "page": int(page),
            "pages": int(pages),
            "scenarios": [self.results(owner, event, include_rows=False) for event in events],
        }

    def results(self, owner, event, include_rows=True):
        record, job = self.load(owner, event)
        if record is None:
            return {"missing": True}
        rows = [json.loads(raw) for raw in self.execute("rows", owner, [f"recipients:{event}"])]
        by_slot = {(row["user_id"], row["channel"]): row for row in rows}
        projected = [
            {
                key: row[key]
                for key in ("user_id", "channel", "status", "reason", "name", "evidence_note")
                if key in row
            }
            for user in job["selected"]
            for channel in ("email", "sms")
            for row in [
                by_slot.get(
                    (user, channel),
                    {
                        "user_id": user,
                        "channel": channel,
                        "status": "pending",
                        "reason": "Waiting for consumer.",
                    },
                )
            ]
        ]
        counts = {
            status: sum(row["status"] == status for row in projected)
            for status in ("pending", "skipped", "accepted", "delivered", "failed", "unknown")
        }
        for row in projected:
            source = by_slot.get((row["user_id"], row["channel"]), {})
            if "masked_destination" in source:
                row["destination"] = source["masked_destination"]
        return {
            "event_id": event,
            "submitted_at_ms": record["submitted_at_ms"],
            "event": record["scenario"]["event"],
            "forecast_url": job["forecast_url"],
            "queue_status": job["queue_status"],
            "counts": counts,
            **({"recipients": projected} if include_rows else {}),
        }

    def next_command(self, owner, consumer):
        rows = self.execute("consume", owner, ["queue"], GROUP, consumer, RECOVERY_IDLE_MS)
        if not rows:
            return None
        message_id, fields = rows[0]
        return message_id, dict(zip(fields[::2], fields[1::2], strict=True))

    def ack(self, owner, message_id):
        # XACK never creates a deleted stream.
        self.client.xack(self.key(owner, "queue"), GROUP, message_id)

    def recover_publications(self, owner):
        for event in self.execute("outbox", owner, ["outbox"]):
            self.publish(owner, event)

    def poll_candidate(self, owner):
        result = self.execute("poll", owner, ["sms-polls"], self.key(owner, ""))
        return (result[0], json.loads(result[1])) if result else None

    def reconcile_sms(self, owner, event, row, outcome):
        return self.execute(
            "reconcile_sms",
            owner,
            [f"recipients:{event}", "references", "sms-polls"],
            f"{row['user_id']}:sms",
            row["token"],
            row["provider_reference"],
            event,
            outcome.status,
            outcome.error_code or "",
            json.dumps(outcome.evidence),
        )
