import assert from 'node:assert/strict';
import test from 'node:test';
import { once } from 'node:events';
import { createApp } from '../../src/interface/http/app.js';
import type { AlertReconciler } from '../../src/ports/alertDelivery.js';

const now = () => new Date('2026-10-11T00:00:00Z');
const attempt = '11111111-1111-4111-8111-111111111111';
const payload = { event: 'delivered', 'message-id': '<fixture@brevo>', ts_event: 1791676800,
  'X-Mailin-custom': `quakestrike-attempt:${attempt}` };

test('authenticated Brevo callback reconciles normalized evidence through the public app', async () => {
  const received: unknown[] = [];
  const app = createApp({ check: async () => {}, search: async () => [], findById: async () => null }, now,
    undefined, { token: 'TEST_ONLY_CALLBACK_TOKEN', reconciler: { reconcile: async input => {
      received.push(input); return 'applied';
    } } });
  const server = app.listen(0, '127.0.0.1'); await once(server, 'listening');
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('No test address');
  try {
    const response = await fetch(`http://127.0.0.1:${address.port}/api/v1/callbacks/brevo`, {
      method: 'POST', headers: { authorization: 'Bearer TEST_ONLY_CALLBACK_TOKEN', 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    });
    assert.equal(response.status, 204);
    assert.deepEqual(received, [{ attemptId: attempt, reference: 'fixture@brevo', status: 'delivered',
      providerTime: '2026-10-11T00:00:00.000Z', errorCode: null }]);
  } finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
});

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
