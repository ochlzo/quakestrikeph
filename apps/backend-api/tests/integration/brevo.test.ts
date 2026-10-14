import assert from 'node:assert/strict';
import test from 'node:test';
import { randomUUID } from 'node:crypto';
import { once } from 'node:events';
import { Pool } from 'pg';
import { createApp } from '../../src/interface/http/app.js';
import { PostgresBrevoReconciler } from '../../src/infrastructure/postgres/brevo.js';
import { createClient } from 'redis';
import { RedisTestBrevoReconciler } from '../../src/infrastructure/redis/testBrevo.js';

const backendUrl = process.env.TEST_BACKEND_DATABASE_URL;
const adminUrl = process.env.TEST_DATABASE_URL;
test('restricted Backend callback commits its narrow capability and retains read-only defaults', { skip: !backendUrl }, async () => {
  if (!backendUrl) return;
  if (new URL(backendUrl).pathname !== '/quakestrike_test') throw new Error('Requires disposable test database');
  const pool = new Pool({ connectionString: backendUrl, max: 1 });
  const app = createApp({ check: async () => {}, search: async () => [], findById: async () => null }, undefined,
    undefined, { token: 'TEST_ONLY_CALLBACK_TOKEN', reconciler: new PostgresBrevoReconciler(pool) });
  const server = app.listen(0, '127.0.0.1'); await once(server, 'listening');
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('No test address');
  try {
    assert.equal(await new PostgresBrevoReconciler(pool).reconcile({ attemptId: randomUUID(),
      reference: 'unmatched-fixture', status: 'delivered', providerTime: '2026-10-11T00:00:00Z', errorCode: null }), 'uncorrelated');
    const response = await fetch(`http://127.0.0.1:${address.port}/api/v1/callbacks/brevo`, { method: 'POST',
      headers: { authorization: 'Bearer TEST_ONLY_CALLBACK_TOKEN', 'content-type': 'application/json' },
      body: JSON.stringify({ event: 'delivered', 'message-id': 'unmatched-fixture', ts_event: 1791676800,
        'X-Mailin-custom': `quakestrike-attempt:${randomUUID()}` }),
    });
    assert.equal(response.status, 429);
    assert.equal(response.headers.get('retry-after'), '60');
    assert.equal((await pool.query('SHOW transaction_read_only')).rows[0].transaction_read_only, 'on');
    await assert.rejects(pool.query('SELECT * FROM alert_delivery_attempts'), { code: '42501' });
    await assert.rejects(pool.query('UPDATE alert_recipients SET status=status'), error =>
      !!error && typeof error === 'object' && 'code' in error && ['25006', '42501'].includes(String(error.code)));
  } finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); await pool.end(); }
});

test('test callbacks reconcile active Redis attempts with ordering, isolation, closure and outage gates', { skip: !process.env.TEST_REDIS_URL }, async () => {
  if (new URL(process.env.TEST_REDIS_URL!).hostname !== 'redis-test') throw new Error('Requires isolated Compose redis-test');
  const redis = createClient({ url: process.env.TEST_REDIS_URL!, disableOfflineQueue: true });
  await redis.connect();
  const control = 'quakestrike:alert-testing:session', session = randomUUID(), event = randomUUID(), attempt = randomUUID();
  const prefix = `quakestrike:alert-testing:${session}:`, slot = `${randomUUID()}:email`;
  const keys = [control, `${prefix}attempts:${event}`, `${prefix}recipients:${event}`, `${prefix}references`];
  const deadline = Date.now() + 60000;
  let productionCalls = 0;
  const app = createApp({ check: async () => {}, search: async () => [], findById: async () => null }, undefined,
    undefined, { token: 'TEST_ONLY_CALLBACK_TOKEN', reconciler: { reconcile: async () => { productionCalls++; return 'applied'; } },
      testReconciler: new RedisTestBrevoReconciler(redis) });
  const server = app.listen(0, '127.0.0.1'); await once(server, 'listening');
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('No test address');
  const callback = (status: string, seconds = 1791676800, reference = 'test-fixture@brevo', authorization = 'Bearer TEST_ONLY_CALLBACK_TOKEN') =>
    fetch(`http://127.0.0.1:${address.port}/api/v1/callbacks/brevo`, { method: 'POST', headers: { authorization, 'content-type': 'application/json' },
      body: JSON.stringify({ event: status, ts_event: seconds, 'message-id': `<${reference}>`,
        'X-Mailin-custom': `quakestrike-attempt:test:${session}:${event}:${attempt}` }) });
  const read = async () => JSON.parse((await redis.hGet(keys[2]!, slot))!);
  let ownsFixture = false;
  try {
    assert.equal(await redis.exists(control), 0, 'Requires disposable Redis without another active session');
    ownsFixture = true;
    // Disposable fixture follows the Python pre-call row and index contract.
    await redis.hSet(control, { session_id: session, lifecycle: 'active', expires_at_ms: String(deadline) });
    await redis.pExpireAt(control, deadline + 86400000);
    await redis.hSet(keys[1]!, attempt, slot); await redis.pExpireAt(keys[1]!, deadline);
    await redis.hSet(keys[2]!, slot, JSON.stringify({ token: attempt, attempt_id: attempt, channel: 'email',
      user_id: slot.split(':')[0], status: 'unknown', reason: 'Provider call reserved; outcome not confirmed.' }));
    await redis.pExpireAt(keys[2]!, deadline);
    assert.equal((await callback('delivered', undefined, undefined, 'Bearer WRONG')).status, 401);
    assert.equal((await read()).status, 'unknown');
    assert.equal((await callback('request')).status, 204);
    assert.equal((await read()).status, 'accepted');
    assert.equal((await callback('request')).status, 204);
    assert.equal((await callback('hard_bounce', 1791676801)).status, 204);
    assert.equal((await callback('request', 1791676802)).status, 204);
    assert.equal((await read()).status, 'failed');
    assert.equal((await callback('delivered', 1791676800)).status, 204);
    assert.equal((await read()).status, 'failed');
    assert.equal((await callback('delivered', 1791676801)).status, 204);
    const delivered = await read(); assert.equal(delivered.status, 'delivered'); assert.equal(delivered.error_code, null);
    assert.equal((await callback('blocked', 1791676802)).status, 204);
    assert.deepEqual(await read(), delivered);
    assert.equal((await callback('delivered', 1791676802, 'conflicting')).status, 409);
    assert.deepEqual(await read(), delivered);
    assert.equal(await redis.pExpireTime(keys[3]!), deadline);
    assert.equal(await redis.pExpireTime(keys[2]!), deadline);
    assert.equal(productionCalls, 0);

    await redis.hSet(keys[3]!, 'email:test-fixture@brevo', 'another-attempt');
    assert.equal((await callback('delivered')).status, 409);
    assert.deepEqual(await read(), delivered);
    await redis.hSet(keys[3]!, 'email:test-fixture@brevo', `${event}:${attempt}`);
    await redis.hDel(control, 'expires_at_ms');
    assert.equal((await callback('delivered')).status, 429);
    await redis.hSet(control, 'expires_at_ms', String(deadline));

    await redis.hSet(control, 'lifecycle', 'closed');
    const ttl = await redis.pTTL(control);
    assert.equal((await callback('delivered')).status, 204);
    assert.ok((await redis.pTTL(control)) <= ttl);
    await redis.del(keys.slice(1));
    assert.equal((await callback('delivered')).status, 204);
    assert.equal((await redis.keys(`${prefix}*`)).length, 0);
    await redis.hSet(control, { lifecycle: 'active', session_id: randomUUID() });
    assert.equal((await callback('delivered')).status, 204);
    await redis.hSet(control, { session_id: session, expires_at_ms: '1' });
    assert.equal((await callback('delivered')).status, 204);
    await redis.del(control);
    assert.equal((await callback('delivered')).status, 204);
    assert.equal((await redis.keys(`${prefix}*`)).length, 0);
    await redis.hSet(control, { session_id: session, lifecycle: 'active', expires_at_ms: String(deadline) });
    const unresolved = await callback('delivered');
    assert.equal(unresolved.status, 429); assert.equal(unresolved.headers.get('retry-after'), '60');
    await redis.del(keys); await redis.quit();
    const outage = await callback('delivered');
    assert.equal(outage.status, 429); assert.equal(outage.headers.get('retry-after'), '60');
    assert.equal(productionCalls, 0);
  } finally {
    server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve()));
    if (redis.isOpen) { if (ownsFixture) await redis.del(keys); await redis.quit(); }
  }
});

test('authenticated early callbacks reconcile atomically and retain duplicate older and late evidence', { skip: !backendUrl || !adminUrl }, async () => {
  if (!backendUrl || !adminUrl) return;
  if ([backendUrl, adminUrl].some(value => new URL(value).pathname !== '/quakestrike_test')) throw new Error('Requires disposable test database');
  const admin = new Pool({ connectionString: adminUrl }), restricted = new Pool({ connectionString: backendUrl, max: 1 });
  const ids = { run: randomUUID(), event: randomUUID(), revision: randomUUID(), release: randomUUID(), prediction: randomUUID(),
    forecast: randomUUID(), alert: randomUUID(), user: randomUUID(), recipient: randomUUID(), attempt: randomUUID() };
  const reference = `fixture-${ids.attempt}@brevo`;
  const app = createApp({ check: async () => {}, search: async () => [], findById: async () => null },
    () => new Date('2026-10-13T00:00:00Z'), undefined,
    { token: 'TEST_ONLY_CALLBACK_TOKEN', reconciler: new PostgresBrevoReconciler(restricted) });
  const server = app.listen(0, '127.0.0.1'); await once(server, 'listening');
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('No test address');
  const callback = (event: string, seconds: number, message = reference, tagged = true, authorization = 'Bearer TEST_ONLY_CALLBACK_TOKEN') =>
    fetch(`http://127.0.0.1:${address.port}/api/v1/callbacks/brevo`, { method: 'POST',
      headers: { authorization, 'content-type': 'application/json' }, body: JSON.stringify({ event,
        'message-id': `<${message}>`, ts_event: seconds,
        ...(tagged ? { 'X-Mailin-custom': `quakestrike-attempt:${ids.attempt}` } : {}) }),
    });
  try {
    await admin.query("INSERT INTO ingestion_runs(run_id,trigger_type,correlation_id) VALUES($1,'manual',$2)", [ids.run, randomUUID()]);
    await admin.query('INSERT INTO earthquake_events(event_id,first_seen_run_id,last_seen_run_id) VALUES($1,$2,$2)', [ids.event, ids.run]);
    await admin.query(`INSERT INTO earthquake_event_revisions(event_revision_id,event_id,revision_number,ingestion_run_id,
      source_event_group_id,source_url,source_time_precision,event_time,latitude,longitude,depth_km,magnitude,location_description)
      VALUES($1,$2,1,$3,$4,'https://example.invalid/bulletin','minute','2026-10-10T00:00:00Z',7,125,12,4.2,'Fixture location')`,
      [ids.revision, ids.event, ids.run, `GROUP_${ids.revision.slice(0, 8).toUpperCase()}`]);
    await admin.query(`INSERT INTO model_releases(model_release_id,version_label,artifact_manifest_uri,artifact_manifest_hash,input_schema_version,output_schema_version)
      VALUES($1,$2,'test://manifest',$3,'input.v1','output.v2')`, [ids.release, `brevo_${ids.release}`, 'a'.repeat(64)]);
    const snapshot = JSON.stringify({ anchor_magnitude: 4.2, anchor_depth_km: 12, anchor_latitude: 7, anchor_longitude: 125,
      anchor_time_is_minute_precision: 1, catalog_m1_plus_count_past_1h: 0, catalog_m1_plus_count_past_24h: 0,
      catalog_m1_plus_count_past_7d: 0, local_m1_plus_count_past_24h_within_50km: 0, local_m1_plus_count_past_24h_within_100km: 0 });
    await admin.query(`INSERT INTO prediction_jobs(job_id,event_revision_id,model_release_id,input_snapshot_hash,input_snapshot_json,
      idempotency_key,status,requested_at,completed_at,correlation_id) VALUES($1,$2,$3,quakestrike_prediction_input_snapshot_sha256($4::jsonb),
      $4::jsonb,$5,'succeeded','2026-10-10T00:00:00Z','2026-10-10T00:00:00Z',$6)`,
      [ids.prediction, ids.revision, ids.release, snapshot, ids.prediction, randomUUID()]);
    await admin.query(`INSERT INTO forecasts(forecast_id,job_id,window_start,window_end,probability_m1_plus_24h,expected_m1_plus_count_24h,
      probability_m4_plus_24h,probability_m5_plus_24h) VALUES($1,$2,'2026-10-10T00:00:00Z','2026-10-11T00:00:00Z',0.7,1.2,0.2,0.05)`,
      [ids.forecast, ids.prediction]);
    await admin.query(`INSERT INTO alert_jobs(alert_job_id,forecast_id,requested_at,message_snapshot,recipient_policy_snapshot,expires_at,correlation_id)
      VALUES($1,$2,'2026-10-10T00:00:00Z','Frozen fixture','{}','2026-10-11T00:00:00Z',$3)`, [ids.alert, ids.forecast, randomUUID()]);
    await admin.query(`INSERT INTO users(user_id,clerk_user_id,display_name,email)
      VALUES($1::uuid,($1::uuid)::text,'Fixture','fixture@example.invalid')`, [ids.user]);
    await admin.query(`INSERT INTO alert_recipients(recipient_id,alert_job_id,channel,destination_snapshot,eligibility_snapshot,delivery_idempotency_key,
      status,processing_lease_expires_at,worker_execution_id,user_id) VALUES($1::uuid,$2,'email','fixture@example.invalid','{}',($1::uuid)::text,'sending',now()+interval '5 minutes',$3,$4)`,
      [ids.recipient, ids.alert, randomUUID(), ids.user]);
    await admin.query(`INSERT INTO alert_delivery_attempts(delivery_attempt_id,recipient_id,attempt_number,provider,correlation_id,content_variant,eligibility_snapshot)
      VALUES($1,$2,1,'brevo',$3,'general','{}')`, [ids.attempt, ids.recipient, randomUUID()]);
    assert.equal((await callback('delivered', 1791676800, reference, true, 'Bearer WRONG')).status, 401);
    assert.equal((await admin.query('SELECT status,provider_message_id FROM alert_delivery_attempts WHERE delivery_attempt_id=$1', [ids.attempt])).rows[0].status, 'sending');
    assert.equal((await callback('request', 1791676800)).status, 204);
    let row = (await admin.query(`SELECT a.status,a.provider_message_id,r.status AS recipient_status FROM alert_delivery_attempts a
      JOIN alert_recipients r USING(recipient_id) WHERE a.delivery_attempt_id=$1`, [ids.attempt])).rows[0];
    assert.equal(row.status, 'accepted'); assert.equal(row.recipient_status, 'accepted'); assert.equal(row.provider_message_id, reference);
    assert.equal((await callback('request', 1791676800)).status, 204);
    assert.equal((await callback('hard_bounce', 1791676801)).status, 204);
    assert.equal((await callback('request', 1791676800)).status, 204);
    row = (await admin.query(`SELECT a.status,a.error_code,r.status AS recipient_status,r.next_attempt_at
      FROM alert_delivery_attempts a JOIN alert_recipients r USING(recipient_id) WHERE a.delivery_attempt_id=$1`, [ids.attempt])).rows[0];
    assert.equal(row.status, 'failed'); assert.equal(row.recipient_status, 'failed');
    assert.equal(row.error_code, 'brevo_hard_bounce'); assert.equal(row.next_attempt_at, null);
    await admin.query("UPDATE alert_jobs SET status='expired',completed_at='2026-10-11T00:00:00Z' WHERE alert_job_id=$1", [ids.alert]);
    assert.equal((await callback('delivered', 1791763200, reference, false)).status, 204);
    assert.equal((await callback('blocked', 1791763201)).status, 204);
    assert.equal((await callback('delivered', 1791763200, 'conflicting-reference')).status, 409);
    row = (await admin.query(`SELECT a.status,a.provider_message_id,a.error_code,a.provider_status_at,r.status AS recipient_status,
      r.next_attempt_at,r.worker_execution_id FROM alert_delivery_attempts a JOIN alert_recipients r USING(recipient_id)
      WHERE a.delivery_attempt_id=$1`, [ids.attempt])).rows[0];
    assert.equal(row.status, 'delivered'); assert.equal(row.recipient_status, 'delivered'); assert.equal(row.error_code, null);
    assert.equal(row.provider_message_id, reference); assert.equal(row.next_attempt_at, null); assert.equal(row.worker_execution_id, null);
    assert.equal(row.provider_status_at.toISOString(), '2026-10-12T00:00:00.000Z');
    assert.equal((await admin.query('SELECT status FROM alert_jobs WHERE alert_job_id=$1', [ids.alert])).rows[0].status, 'expired');
    assert.equal((await restricted.query('SHOW transaction_read_only')).rows[0].transaction_read_only, 'on');
  } finally {
    server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve()));
    for (const [table, column, id] of [['alert_delivery_attempts','delivery_attempt_id',ids.attempt], ['alert_recipients','recipient_id',ids.recipient],
      ['users','user_id',ids.user],
      ['alert_jobs','alert_job_id',ids.alert], ['forecasts','forecast_id',ids.forecast], ['prediction_jobs','job_id',ids.prediction],
      ['earthquake_event_revisions','event_revision_id',ids.revision], ['earthquake_events','event_id',ids.event],
      ['model_releases','model_release_id',ids.release], ['ingestion_runs','run_id',ids.run]]) {
      await admin.query(`DELETE FROM ${table} WHERE ${column}=$1`, [id]);
    }
    await restricted.end(); await admin.end();
  }
});
