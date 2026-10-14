import type { RedisClientType } from 'redis';
import { DataUnavailable } from '../../application/information/errors.js';
import type { SyntheticScenarioReader } from '../../ports/syntheticScenarioReader.js';
import { projectSubmittedScenario } from '../../domain/submittedScenario.js';

const readScript = `
local session = redis.call('HGET', KEYS[1], 'session_id')
if not session then return nil end
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local deadline = tonumber(redis.call('HGET', KEYS[1], 'expires_at_ms'))
if not deadline then return redis.error_reply('Invalid session deadline') end
if redis.call('HGET', KEYS[1], 'lifecycle') ~= 'active' or deadline <= now then return nil end
local key = ARGV[1] .. session .. ':scenario:' .. ARGV[2]
if redis.call('EXISTS', key) == 0 then key = ARGV[1] .. session .. ':preview:' .. ARGV[2] end
if redis.call('STRLEN', key) > 262144 then return redis.error_reply('Oversized scenario') end
local raw = redis.call('GET', key)
if not raw then return nil end
return {raw, session, tostring(deadline)}
`;

export class RedisSyntheticScenarioReader implements SyntheticScenarioReader {
  constructor(private redis: RedisClientType) {}

  async findSubmitted(eventId: string) {
    try {
      if (!this.redis.isReady) throw new Error('Redis unavailable');
      const result = await this.redis.withCommandOptions({ abortSignal: AbortSignal.timeout(2000) }).eval(readScript, {
        keys: ['quakestrike:alert-testing:session'], arguments: ['quakestrike:alert-testing:', eventId],
      });
      if (result === null) return null;
      if (!Array.isArray(result) || result.length !== 3 || typeof result[0] !== 'string' || typeof result[1] !== 'string') {
        throw new Error('Invalid storage response');
      }
      return projectSubmittedScenario(JSON.parse(result[0]), result[1], Number(result[2]), eventId);
    } catch {
      throw new DataUnavailable('Synthetic data is temporarily unavailable');
    }
  }
}
