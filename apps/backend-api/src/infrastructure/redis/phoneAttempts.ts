import { createHash, randomUUID } from 'node:crypto';
import type { RedisClientType } from 'redis';
import { AccountError } from '../../domain/accounts.js';
import type { PendingPhone, PhoneAttempts } from '../../ports/accounts.js';

const digest = (value: string) => createHash('sha256').update(value).digest('hex');
const userKey = (id: string) => `bulletin:phone:user:${digest(id)}`;
const ownerKey = (phone: string) => `bulletin:phone:owner:${digest(phone)}`;
const expired = () => new AccountError('ATTEMPT_EXPIRED', 'Request a new code to continue.', 'code');

export class RedisPhoneAttempts implements PhoneAttempts {
  constructor(private redis: RedisClientType) {}
  private async eval(script: string, keys: string[], args: string[] = []) {
    if (!this.redis.isReady) throw new AccountError('VERIFICATION_UNAVAILABLE', 'Mobile verification is temporarily unavailable.');
    try { return await this.redis.eval(script, { keys, arguments: args }); }
    catch { throw new AccountError('VERIFICATION_UNAVAILABLE', 'Mobile verification is temporarily unavailable.'); }
  }
  async exclusive<T>(user: string, phone: string | null, work: () => Promise<T>): Promise<T> {
    const keys = [`${userKey(user)}:lock`];
    if (phone !== null) keys.push(`${ownerKey(phone)}:lock`);
    const token = randomUUID();
    const acquired = await this.eval(`
      for _,k in ipairs(KEYS) do if redis.call('EXISTS',k)==1 then return 0 end end
      for _,k in ipairs(KEYS) do redis.call('SET',k,ARGV[1],'PX',60000) end return 1`, keys, [token]);
    if (acquired !== 1) throw new AccountError('VERIFICATION_BUSY', 'A verification request is already running. Try again shortly.');
    try { return await work(); }
    finally {
      // A failed unlock must not turn a committed operation into false failure.
      // The bounded lock TTL releases it even when Redis disconnects here.
      await this.eval(`for _,k in ipairs(KEYS) do if redis.call('GET',k)==ARGV[1] then redis.call('DEL',k) end end return 1`, keys, [token]).catch(() => {});
    }
  }
  async start(user: string, phone: string) {
    const now = Date.now();
    const pending = { id: randomUUID(), phone, expiresAt: new Date(now + 300000).toISOString(),
      resendAt: new Date(now + 60000).toISOString(), failures: 0, owner: ownerKey(phone) };
    const u = userKey(user), p = ownerKey(phone);
    const result = await this.eval(`
      if redis.call('EXISTS',KEYS[3])==1 or redis.call('EXISTS',KEYS[4])==1 then return 'cooldown' end
      for i=5,8 do
        local limit=3; if i>=7 then limit=10 end
        local window=3600000; if i>=7 then window=86400000 end
        redis.call('ZREMRANGEBYSCORE',KEYS[i],'-inf',tonumber(ARGV[3])-window)
        if redis.call('ZCARD',KEYS[i])>=limit then return 'limit' end
      end
      local old=redis.call('GET',KEYS[1])
      if old then
        local a=cjson.decode(old)
        if redis.call('GET',a.owner)==a.id then redis.call('DEL',a.owner) end
      end
      for i=5,8 do
        local ttl=3600; if i>=7 then ttl=86400 end
        redis.call('ZADD',KEYS[i],ARGV[3],ARGV[2]); redis.call('EXPIRE',KEYS[i],ttl)
      end
      redis.call('SET',KEYS[3],'1','EX',60); redis.call('SET',KEYS[4],'1','EX',60)
      redis.call('SET',KEYS[1],ARGV[1],'EX',300); redis.call('SET',KEYS[2],ARGV[2],'EX',300)
      return 'ok'`, [u, p, `${u}:cooldown`, `${p}:cooldown`, `${u}:hour`, `${p}:hour`, `${u}:day`, `${p}:day`],
    [JSON.stringify(pending), pending.id, String(now)]);
    if (result !== 'ok') throw new AccountError('SEND_LIMIT', result === 'cooldown' ?
      'Wait 60 seconds between code requests.' : 'You have reached the verification send limit. Try again later.');
    return this.public(pending);
  }
  private public(p: PendingPhone): PendingPhone {
    return { id: p.id, phone: p.phone, expiresAt: p.expiresAt, resendAt: p.resendAt };
  }
  async pending(user: string) {
    const result = await this.eval(`
      local raw=redis.call('GET',KEYS[1]); if not raw then return nil end
      local p=cjson.decode(raw)
      if redis.call('GET',p.owner)~=p.id then redis.call('DEL',KEYS[1]); return nil end
      return raw`, [userKey(user)]);
    return typeof result === 'string' ? this.public(JSON.parse(result) as PendingPhone) : null;
  }
  async check(user: string, attemptId: string) {
    const p = await this.pending(user);
    if (!p || p.id !== attemptId || Date.parse(p.expiresAt) <= Date.now()) throw expired();
    return p;
  }
  async arm(user: string, attemptId: string, proof: string) {
    const result = await this.eval(`
      local raw=redis.call('GET',KEYS[1]); if not raw then return 0 end
      local p=cjson.decode(raw); if p.id~=ARGV[1] or redis.call('GET',p.owner)~=p.id then return 0 end
      local ttl=redis.call('PTTL',KEYS[1]); if ttl<=0 then return 0 end
      p.proof=ARGV[2]; redis.call('SET',KEYS[1],cjson.encode(p),'PX',ttl); return 1`, [userKey(user)], [attemptId, proof]);
    if (result !== 1) throw expired();
  }
  async matches(user: string, attemptId: string, proof: string) {
    const result = await this.eval(`
      local raw=redis.call('GET',KEYS[1]); if not raw then return 0 end
      local p=cjson.decode(raw); if p.id~=ARGV[1] or redis.call('GET',p.owner)~=p.id then return 0 end
      if not p.proof then return 0 end
      if p.proof~=ARGV[2] then return 0 end return 1`, [userKey(user)], [attemptId, proof]);
    return result === 1;
  }
  async wrong(user: string, attemptId: string) {
    const result = await this.eval(`
      local raw=redis.call('GET',KEYS[1]); if not raw then return 0 end
      local p=cjson.decode(raw); if p.id~=ARGV[1] or redis.call('GET',p.owner)~=p.id then return 0 end
      p.failures=p.failures+1
      if p.failures>=5 then redis.call('DEL',KEYS[1],p.owner); return 0 end
      local ttl=redis.call('PTTL',KEYS[1]); if ttl<=0 then return 0 end
      redis.call('SET',KEYS[1],cjson.encode(p),'PX',ttl); return 1`, [userKey(user)], [attemptId]);
    if (result !== 1) throw expired();
  }
  async consume(user: string, attemptId: string) {
    const result = await this.eval(`
      local raw=redis.call('GET',KEYS[1]); if not raw then return 0 end
      local p=cjson.decode(raw); if p.id~=ARGV[1] or redis.call('GET',p.owner)~=p.id then return 0 end
      redis.call('DEL',KEYS[1],p.owner); return 1`, [userKey(user)], [attemptId]);
    if (result !== 1) throw expired();
  }
  async cancel(user: string) {
    const p = await this.pending(user);
    if (p) await this.consume(user, p.id);
  }
}
