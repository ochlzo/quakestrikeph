import type { RedisClientType } from 'redis';
import type { TestAlertReconciler, TestBrevoEvidence, ReconcileOutcome } from '../../ports/alertDelivery.js';

const reconcileScript = `
local clock = redis.call('TIME')
local now = tonumber(clock[1])*1000 + math.floor(tonumber(clock[2])/1000)
if redis.call('HGET', KEYS[1], 'session_id') ~= ARGV[1] then return 'ignored' end
local lifecycle = redis.call('HGET', KEYS[1], 'lifecycle')
if lifecycle == 'closed' or lifecycle == 'expired' then return 'ignored' end
local deadline = tonumber(redis.call('HGET', KEYS[1], 'expires_at_ms'))
if lifecycle ~= 'active' or not deadline then return redis.error_reply('Invalid test session') end
if now >= deadline then return 'ignored' end
local slot = redis.call('HGET', KEYS[2], ARGV[2])
if not slot then return 'uncorrelated' end
local raw = redis.call('HGET', KEYS[3], slot)
if not raw then return 'uncorrelated' end
local row = cjson.decode(raw)
if row.token ~= ARGV[2] or row.channel ~= 'email' or row.status == 'skipped' then return 'conflict' end
local reference = ARGV[3]
local identity = ARGV[4] .. ':' .. ARGV[2]
local mapped = redis.call('HGET', KEYS[4], 'email:' .. reference)
if (row.provider_reference and row.provider_reference ~= cjson.null and row.provider_reference ~= reference)
 or (mapped and mapped ~= identity) then return 'conflict' end
local at = tonumber(ARGV[6])
local previous = tonumber(row.provider_status_at_ms or '0')
local rank = {accepted=1, failed=2, delivered=3}
local status = ARGV[5]
if row.status == 'delivered' or (row.status == 'failed' and status == 'accepted')
 or at < previous or (at == previous and (rank[row.status] or 0) >= rank[status]) then return 'ignored' end
redis.call('HSET', KEYS[4], 'email:' .. reference, identity)
redis.call('PEXPIREAT', KEYS[4], deadline)
row.provider_reference = reference
row.status = status
row.provider_status_at_ms = at
row.error_code = ARGV[7] ~= '' and ARGV[7] or cjson.null
row.reason = status == 'delivered' and 'Provider confirmed delivery.'
 or status == 'failed' and 'Provider reported delivery failure.'
 or 'Provider accepted the request; delivery is not confirmed.'
redis.call('HSET', KEYS[3], slot, cjson.encode(row))
return 'applied'
`;

export class RedisTestBrevoReconciler implements TestAlertReconciler {
  constructor(private redis: RedisClientType) {}
  async reconcile(evidence: TestBrevoEvidence): Promise<ReconcileOutcome> {
    if (!this.redis.isReady) throw new Error('Test reconciliation unavailable');
    const prefix = `quakestrike:alert-testing:${evidence.testSessionId}:`;
    // AbortSignal bounds queued commands; the race also bounds a stalled written command.
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const outcome = await Promise.race([
        this.redis.withCommandOptions({ abortSignal: AbortSignal.timeout(2000) }).eval(reconcileScript, {
          keys: ['quakestrike:alert-testing:session', `${prefix}attempts:${evidence.testEventId}`,
            `${prefix}recipients:${evidence.testEventId}`, `${prefix}references`],
          arguments: [evidence.testSessionId, evidence.attemptId, evidence.reference, evidence.testEventId,
            evidence.status, String(Date.parse(evidence.providerTime)), evidence.errorCode ?? ''],
        }),
        new Promise<never>((_resolve, reject) => { timer = setTimeout(() => reject(new Error('Test reconciliation timeout')), 2000); }),
      ]);
      if (typeof outcome !== 'string' || !['applied', 'ignored', 'uncorrelated', 'conflict'].includes(outcome)) {
        throw new Error('Invalid test reconciliation result');
      }
      return outcome as ReconcileOutcome;
    } finally { clearTimeout(timer); }
  }
}
