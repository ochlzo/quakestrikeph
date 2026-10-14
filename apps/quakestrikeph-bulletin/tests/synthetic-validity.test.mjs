import assert from 'node:assert/strict';
import test from 'node:test';
import { monitorSyntheticForecast } from '../src/lib/api/synthetic-validity.ts';
import { loadObservationWindow } from '../src/lib/api/forecast-observations.ts';
import { ForecastObservationCache } from '../src/lib/forecast-observation-cache.ts';

const id = '11111111-1111-4111-8111-111111111111';
const now = Date.parse('2026-10-13T12:00:00Z');
const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

function setup(t, expiry = now + 3600000) {
  t.mock.timers.enable({ apis: ['Date', 'setTimeout', 'setInterval'], now });
  const window = new EventTarget(), document = new EventTarget();
  let reloads = 0, hidden = 0, invalidations = 0;
  window.location = { reload: () => reloads++ };
  document.body = { dataset: { syntheticEvent: id, syntheticExpiry: new Date(expiry).toISOString() } };
  document.querySelector = () => ({ setAttribute: () => hidden++ });
  window.addEventListener('synthetic-forecast-invalidated', () => invalidations++);
  t.mock.method(globalThis, 'fetch', async () => new Response('{}'));
  const priorWindow = globalThis.window, priorDocument = globalThis.document;
  globalThis.window = window; globalThis.document = document;
  t.after(() => { globalThis.window = priorWindow; globalThis.document = priorDocument; });
  return { window, document, reloads: () => reloads, hidden: () => hidden, invalidations: () => invalidations };
}

test('open synthetic page rechecks closure and removes cached success before reload', async t => {
  const f = setup(t);
  monitorSyntheticForecast(); await settle();
  assert.equal(f.reloads(), 0);
  assert.equal(fetch.mock.calls[0].arguments[0], `/api/v1/earthquakes/${id}?test=true`);
  assert.equal(fetch.mock.calls[0].arguments[1].cache, 'no-store');
  fetch.mock.mockImplementation(async () => new Response(null, { status: 404 }));
  t.mock.timers.tick(15000); await settle();
  assert.equal(f.reloads(), 1); assert.equal(f.hidden(), 2); assert.equal(f.invalidations(), 1);
  t.mock.timers.tick(60000); await settle(); assert.equal(f.reloads(), 1);
});

test('fixed expiry clears the page without waiting for the next poll', async t => {
  const f = setup(t, now + 1000);
  monitorSyntheticForecast(); await settle();
  t.mock.timers.tick(1000); await settle();
  assert.equal(f.reloads(), 1);
});

test('outage and back/forward cache restoration cannot preserve synthetic success', async t => {
  const f = setup(t);
  monitorSyntheticForecast(); await settle();
  f.window.dispatchEvent(new Event('pagehide'));
  const restore = new Event('pageshow'); restore.persisted = true;
  f.window.dispatchEvent(restore);
  assert.equal(f.reloads(), 1);
});

test('dependency failure on focus reloads through the server unavailable state', async t => {
  const f = setup(t);
  monitorSyntheticForecast(); await settle();
  fetch.mock.mockImplementation(async () => { throw new Error('Redis unavailable'); });
  f.window.dispatchEvent(new Event('focus')); await settle();
  assert.equal(f.reloads(), 1);
});

test('synthetic observation pagination and retries retain their source', async t => {
  setup(t);
  let fail = false;
  fetch.mock.mockImplementation(async (url, options) => {
    assert.equal(url, `/api/v1/earthquakes/${id}/observations?test=true`);
    assert.equal(options.cache, 'no-store');
    if (fail) return new Response(null, { status: 503 });
    const cursor = JSON.parse(options.body).cursor;
    return Response.json({ items: [{ eventId: cursor ? 'older' : 'newer', eventTime: cursor ? '2026-10-13T10:00:00Z' : '2026-10-13T11:00:00Z' }],
      hasMore: !cursor, nextCursor: cursor ? null : 'next-page' });
  });
  const from = '2026-10-13T00:00:00Z', to = '2026-10-14T00:00:00Z';
  assert.deepEqual((await loadObservationWindow(from, to, id)).map(x => x.eventId), ['older', 'newer']);
  fail = true;
  await assert.rejects(() => loadObservationWindow(from, to, id));
  fail = false;
  assert.equal((await loadObservationWindow(from, to, id)).length, 2);
});

test('cache invalidation discards an in-flight success', async () => {
  let finish;
  let active = true;
  const cache = new ForecastObservationCache(now, () => new Promise(resolve => { finish = resolve; }));
  const pending = cache.ensure(now, now + 1000, now + 1000, () => active);
  active = false; cache.clear();
  finish([{ eventId: id, eventTime: new Date(now).toISOString() }]);
  await pending;
  assert.deepEqual(cache.observations(now, now + 1000, 'other'), []);
  assert.equal(cache.covered(now, now + 1000, now + 1000), false);
});
