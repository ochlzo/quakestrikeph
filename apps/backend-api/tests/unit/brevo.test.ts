import assert from 'node:assert/strict';
import test from 'node:test';
import { once } from 'node:events';
import { createApp } from '../../src/interface/http/app.js';
import type { AlertReconciler, TestAlertReconciler } from '../../src/ports/alertDelivery.js';
import type { RedisClientType } from 'redis';
import { RedisTestBrevoReconciler } from '../../src/infrastructure/redis/testBrevo.js';

const now = () => new Date('2026-10-11T00:00:00Z');
const attempt = '11111111-1111-4111-8111-111111111111';
const payload = { event: 'delivered', 'message-id': '<fixture@brevo>', ts_event: 1791676800,
  'X-Mailin-custom': `quakestrike-attempt:${attempt}` };

async function withCallback(reconcile: AlertReconciler['reconcile'], run: (url: string) => Promise<void>) {
  const app = createApp({ check: async () => {}, search: async () => [], findById: async () => null }, now,
    undefined, { token: 'TEST_ONLY_CALLBACK_TOKEN', reconciler: { reconcile } });
  const server = app.listen(0, '127.0.0.1'); await once(server, 'listening');
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('No test address');
  try { await run(`http://127.0.0.1:${address.port}/api/v1/callbacks/brevo`); }
  finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
}
const headers = { authorization: 'Bearer TEST_ONLY_CALLBACK_TOKEN', 'content-type': 'application/json' };

test('callback denies missing, wrong, basic and query credentials before body parsing or database calls', async () => {
  let calls = 0;
  await withCallback(async () => { calls++; return 'applied'; }, async url => {
    for (const authorization of ['', 'Bearer WRONG', 'Basic TEST_ONLY_CALLBACK_TOKEN']) {
      assert.equal((await fetch(url, { method: 'POST', headers: { ...headers, authorization }, body: '{' })).status, 401);
    }
    assert.equal((await fetch(`${url}?token=PRIVATE`, { method: 'POST', headers, body: JSON.stringify(payload) })).status, 401);
    assert.equal(calls, 0);
  });
});

test('callback validation bounds content and timestamps without replacing missing event time', async () => {
  let calls = 0;
  await withCallback(async () => { calls++; return 'applied'; }, async url => {
    for (const bad of [[], { ...payload, event: 'invented' }, { ...payload, 'message-id': '\nPRIVATE' },
      { ...payload, ts_event: undefined, ts_epoch: 1791676800000 }, { ...payload, ts_event: 1791677101 },
      { ...payload, ts_event: 1.5 }, { ...payload, 'X-Mailin-custom': 'malformed-attempt' }]) {
      assert.equal((await fetch(url, { method: 'POST', headers, body: JSON.stringify(bad) })).status, 400);
    }
    assert.equal((await fetch(url, { method: 'POST', headers: { ...headers, 'content-type': 'text/plain' }, body: '{}' })).status, 415);
    assert.equal((await fetch(url, { method: 'POST', headers, body: JSON.stringify({ ...payload, padding: 'x'.repeat(33000) }) })).status, 413);
    assert.equal(calls, 0);
    assert.equal((await fetch(url, { method: 'POST', headers, body: JSON.stringify({ ...payload, padding: 'x'.repeat(9000) }) })).status, 204);
    assert.equal(calls, 1);
  });
});

test('callback processing failures return retryable status without private exception or body logging', async () => {
  const logs: string[] = [], previous = console.error;
  console.error = message => logs.push(String(message));
  try {
    await withCallback(async () => { throw new Error('PRIVATE_SECRET reader@example.invalid'); }, async url => {
      const response = await fetch(url, { method: 'POST', headers, body: JSON.stringify({ ...payload, email: 'reader@example.invalid' }) });
      assert.equal(response.status, 429); assert.equal(response.headers.get('retry-after'), '60');
    });
    assert.equal(logs.length, 1);
    assert.equal(logs.join('').includes('PRIVATE'), false);
    assert.equal(logs.join('').includes('@example.invalid'), false);
    assert.ok(JSON.parse(logs[0]!).requestId);
  } finally { console.error = previous; }
});

test('test marker routes only authenticated validated callbacks to the isolated reconciler', async () => {
  const session = '22222222-2222-4222-8222-222222222222', event = '33333333-3333-4333-8333-333333333333';
  const received: unknown[] = [], production: unknown[] = [];
  let outcome: Awaited<ReturnType<TestAlertReconciler['reconcile']>> = 'applied';
  const app = createApp({ check: async () => {}, search: async () => [], findById: async () => null }, now,
    undefined, { token: 'TEST_ONLY_CALLBACK_TOKEN', reconciler: { reconcile: async evidence => { production.push(evidence); return 'applied'; } },
      testReconciler: { reconcile: async evidence => { received.push(evidence); return outcome; } } });
  const server = app.listen(0, '127.0.0.1'); await once(server, 'listening');
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('No test address');
  const url = `http://127.0.0.1:${address.port}/api/v1/callbacks/brevo`;
  const tagged = { ...payload, 'X-Mailin-custom': `quakestrike-attempt:test:${session}:${event}:${attempt}` };
  const post = (body: unknown, authorization = headers.authorization) => fetch(url, { method: 'POST', headers: { ...headers, authorization }, body: JSON.stringify(body) });
  try {
    assert.equal((await post(tagged, 'Bearer WRONG')).status, 401);
    assert.equal(received.length, 0); assert.equal(production.length, 0);
    for (const marker of [`quakestrike-attempt:test:${session}:${event}`, `quakestrike-attempt:test:${session}:${event}:${attempt}:extra`,
      `quakestrike-attempt:test:invalid:${event}:${attempt}`]) {
      assert.equal((await post({ ...tagged, 'X-Mailin-custom': marker })).status, 400);
    }
    assert.equal((await post(tagged)).status, 204);
    assert.deepEqual(received[0], { attemptId: attempt, testSessionId: session, testEventId: event,
      reference: 'fixture@brevo', status: 'delivered', providerTime: '2026-10-11T00:00:00.000Z', errorCode: null });
    outcome = 'ignored'; assert.equal((await post(tagged)).status, 204);
    outcome = 'conflict'; assert.equal((await post(tagged)).status, 409);
    outcome = 'uncorrelated'; const unresolved = await post(tagged);
    assert.equal(unresolved.status, 429); assert.equal(unresolved.headers.get('retry-after'), '60');
    assert.equal(production.length, 0);
    assert.equal((await post(payload)).status, 204);
    assert.equal(production.length, 1);
  } finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
});

test('missing test storage never falls through to production or acknowledges absence', async () => {
  let calls = 0;
  await withCallback(async () => { calls++; return 'applied'; }, async url => {
    const response = await fetch(url, { method: 'POST', headers, body: JSON.stringify({ ...payload,
      'X-Mailin-custom': `quakestrike-attempt:test:${attempt}:${attempt}:${attempt}` }) });
    assert.equal(response.status, 429); assert.equal(response.headers.get('retry-after'), '60');
    assert.equal(calls, 0);
  });
});

test('test reconciliation bounds a stalled written Redis command and treats unavailable storage as retryable', async () => {
  const evidence = { testSessionId: attempt, testEventId: attempt, attemptId: attempt,
    reference: 'fixture@brevo', status: 'delivered' as const, providerTime: now().toISOString(), errorCode: null };
  const unavailable = new RedisTestBrevoReconciler({ isReady: false } as RedisClientType);
  await assert.rejects(unavailable.reconcile(evidence), /unavailable/);
  const stalled = new RedisTestBrevoReconciler({ isReady: true, withCommandOptions: () => ({ eval: () => new Promise(() => {}) }) } as unknown as RedisClientType);
  const started = Date.now();
  await assert.rejects(stalled.reconcile(evidence), /timeout/);
  assert.ok(Date.now() - started < 5000);
});
