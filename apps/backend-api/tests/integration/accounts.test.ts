import assert from 'node:assert/strict';
import { createHash, randomInt, randomUUID } from 'node:crypto';
import test from 'node:test';
import { Pool } from 'pg';
import { createClient } from 'redis';
import { PostgresAccounts } from '../../src/infrastructure/postgres/accounts.js';
import { RedisPhoneAttempts } from '../../src/infrastructure/redis/phoneAttempts.js';
import type { Identity } from '../../src/domain/accounts.js';

const database = process.env.TEST_DATABASE_URL, backend = process.env.TEST_BACKEND_DATABASE_URL, redisUrl = process.env.TEST_REDIS_URL;
const p = { emailEnabled: false, smsEnabled: false, magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null };
function requireTestDatabase(value: string) {
  if (new URL(value).pathname !== '/quakestrike_test') throw new Error('Requires disposable quakestrike_test database');
}

test('account writes enforce ownership, phone uniqueness, state and atomic audits under Backend grants', { skip: !database || !backend }, async () => {
  if (!database || !backend) return;
  requireTestDatabase(database); requireTestDatabase(backend);
  const admin = new Pool({ connectionString: database }), pool = new Pool({ connectionString: backend });
  const store = new PostgresAccounts(pool), id = randomUUID();
  const identity: Identity = { clerkUserId: `test_${id}`, email: `${id}@example.invalid`, recent: true };
  const other: Identity = { clerkUserId: `test_other_${id}`, email: `other_${id}@example.invalid`, recent: true };
  const phone = `+639${randomInt(100000000, 999999999)}`;
  const users: string[] = [];
  try {
    const [first, same] = await Promise.all([store.profile(identity, 'Reader', randomUUID()), store.profile(identity, 'Reader', randomUUID())]);
    users.push(first.userId); assert.equal(first.userId, same.userId);
    const second = await store.profile(other, 'Other Reader', randomUUID()); users.push(second.userId);
    assert.equal(await store.read({ ...identity, clerkUserId: 'missing_test_user' }), null);
    await assert.rejects(store.read({ ...identity, email: 'changed@example.invalid' }), { code: 'EMAIL_MIRROR_MISMATCH' });
    await store.bindPhone(identity, phone, randomUUID());
    await assert.rejects(store.bindPhone(other, phone, randomUUID()), { code: 'PHONE_UNAVAILABLE' });
    await store.save(identity, { ...p, emailEnabled: true, smsEnabled: true }, randomUUID());
    const paused = await store.pauseSms(identity, randomUUID()); assert.equal(paused.phone, phone); assert.equal(paused.smsEnabled, false);
    assert.equal((await store.save(other, p, randomUUID())).onboardingCompleted, true);
    await assert.rejects(pool.query('SELECT * FROM audit_logs'), { code: '42501' });
    await assert.rejects(pool.query("UPDATE users SET account_status='suspended' WHERE user_id=$1", [first.userId]),
      e => !!e && typeof e === 'object' && 'code' in e && ['25006', '42501'].includes(String(e.code)));
    await admin.query("UPDATE users SET account_status='suspended' WHERE user_id=$1", [first.userId]);
    await assert.rejects(store.save(identity, p, randomUUID()), { code: 'ACCOUNT_UNAVAILABLE' });
    await admin.query("UPDATE users SET account_status='active' WHERE user_id=$1", [first.userId]);
    // Fail only the next success audit via a request-id check; no extra table/column.
    const rejectedRequest = randomUUID();
    await admin.query(`ALTER TABLE audit_logs ADD CONSTRAINT ck_test_reject_account_audit CHECK (request_id <> '${rejectedRequest}'::uuid)`);
    const before = await store.read(identity);
    try {
      await assert.rejects(store.save(identity, { ...p, magnitude: 7.5 }, rejectedRequest), { code: '23514' });
      assert.deepEqual(await store.read(identity), before);
    } finally { await admin.query('ALTER TABLE audit_logs DROP CONSTRAINT ck_test_reject_account_audit'); }
    const audits = await admin.query("SELECT action, metadata FROM audit_logs WHERE actor_user_id=$1 AND outcome='succeeded'", [first.userId]);
    assert.ok(audits.rows.some(row => row.action === 'preferences_saved' && row.metadata.emailEnabled === true));
    assert.equal(JSON.stringify(audits.rows).includes(phone), false);
    const removed = await store.removePhone(identity, randomUUID());
    assert.equal(removed.phone, null); assert.equal(removed.smsEnabled, false);
    assert.equal((await store.read(identity))?.phone, null);
    const removedAt = (await admin.query('SELECT updated_at FROM users WHERE user_id=$1', [first.userId])).rows[0].updated_at;
    const repeated = await Promise.all([
      store.removePhone(identity, randomUUID()),
      store.removePhone(identity, randomUUID()),
    ]);
    for (const result of repeated) assert.deepEqual(result, removed);
    const removal = await admin.query("SELECT action, metadata FROM audit_logs WHERE actor_user_id=$1 AND action='phone_removed'", [first.userId]);
    assert.equal(removal.rowCount, 1);
    assert.deepEqual((await admin.query('SELECT updated_at FROM users WHERE user_id=$1', [first.userId])).rows[0].updated_at,
      removedAt, 'Removing an absent phone must not update the account');
    assert.equal(JSON.stringify(removal.rows).includes(phone), false);
  } finally {
    await admin.query('DELETE FROM audit_logs WHERE actor_user_id = ANY($1::uuid[])', [users]);
    await admin.query('DELETE FROM users WHERE user_id = ANY($1::uuid[])', [users]);
    await pool.end(); await admin.end();
  }
});

test('Redis attempts enforce account/phone fencing, expiry, five wrong codes, cooldown and sliding send limits', { skip: !redisUrl }, async () => {
  if (!redisUrl) return;
  if (!['redis-test', '127.0.0.1', 'localhost'].includes(new URL(redisUrl).hostname)) throw new Error('Requires disposable test Redis');
  const redis = createClient({ url: redisUrl }); await redis.connect();
  const attempts = new RedisPhoneAttempts(redis), user = `test_${randomUUID()}`, other = `test_${randomUUID()}`;
  const phone = `+639${randomInt(100000000, 999999999)}`;
  const hash = (v: string) => createHash('sha256').update(v).digest('hex');
  const u = `bulletin:phone:user:${hash(user)}`, o = `bulletin:phone:user:${hash(other)}`, n = `bulletin:phone:owner:${hash(phone)}`;
  const cooldown = () => redis.del([`${u}:cooldown`, `${o}:cooldown`, `${n}:cooldown`]);
  try {
    const pending = await attempts.start(user, phone); await attempts.arm(user, pending.id, 'FIXTURE_DIGEST');
    assert.equal(await attempts.matches(user, pending.id, 'FIXTURE_DIGEST'), true);
    assert.equal(await attempts.matches(user, pending.id, 'OLD_DIGEST'), false);
    assert.equal(await attempts.pending(other), null);
    await assert.rejects(attempts.check(other, pending.id), { code: 'ATTEMPT_EXPIRED' });
    await assert.rejects(attempts.start(user, phone), { code: 'SEND_LIMIT' });
    assert.ok((await redis.ttl(u)) <= 300);
    for (let i = 0; i < 4; i++) await attempts.wrong(user, pending.id);
    await assert.rejects(attempts.wrong(user, pending.id), { code: 'ATTEMPT_EXPIRED' });
    assert.equal(await attempts.pending(user), null);
    await cooldown(); const old = await attempts.start(user, phone); await cooldown();
    const replacement = await attempts.start(other, phone);
    await assert.rejects(attempts.check(user, old.id), { code: 'ATTEMPT_EXPIRED' });
    await attempts.arm(other, replacement.id, 'NEW_DIGEST');
    await attempts.consume(other, replacement.id);
    await assert.rejects(attempts.consume(other, replacement.id), { code: 'ATTEMPT_EXPIRED' });
    await cooldown(); await assert.rejects(attempts.start(user, phone), { code: 'SEND_LIMIT' });
    // Age only test-owned rate evidence, then confirm expiry is fail-closed.
    await redis.del([`${u}:hour`, `${n}:hour`]);
    const expiry = await attempts.start(user, phone); await redis.del(u);
    await assert.rejects(attempts.check(user, expiry.id), { code: 'ATTEMPT_EXPIRED' });
    let release!: () => void, entered!: () => void;
    const gate = new Promise<void>(resolve => { entered = resolve; });
    const running = attempts.exclusive(user, phone, async () => { entered(); await new Promise<void>(resolve => { release = resolve; }); });
    await gate;
    await assert.rejects(attempts.exclusive(other, phone, async () => {}), { code: 'VERIFICATION_BUSY' });
    await assert.rejects(attempts.exclusive(user, null, async () => {}), { code: 'VERIFICATION_BUSY' });
    release(); await running;
    await attempts.exclusive(user, null, async () => {
      await assert.rejects(attempts.exclusive(user, phone, async () => {}), { code: 'VERIFICATION_BUSY' });
      await attempts.exclusive(other, phone, async () => {});
    });
  } finally {
    for (const prefix of [u, o, n]) await redis.del([prefix, ...['lock', 'cooldown', 'hour', 'day'].map(s => `${prefix}:${s}`)]);
    await redis.close();
  }
});
