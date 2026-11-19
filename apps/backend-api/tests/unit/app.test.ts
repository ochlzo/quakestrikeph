import assert from 'node:assert/strict';
import test from 'node:test';
import type { Server } from 'node:http';
import { once } from 'node:events';
import type { Earthquake } from '../../src/domain/information.js';
import { forecastAvailability } from '../../src/domain/information.js';
import type { EarthquakeReader } from '../../src/ports/earthquakeReader.js';
import { createApp } from '../../src/interface/http/app.js';
import { DataUnavailable } from '../../src/application/information/errors.js';
import { guestCookieLifetimeMs, SimulationGuestCookies, type SimulationRequest } from '../../src/application/forecastSimulations.js';
import type { SimulationDependencies } from '../../src/interface/http/routes/forecastSimulations.js';

const event: Earthquake = {
  eventId: '11111111-1111-4111-8111-111111111111',
  eventRevisionId: '22222222-2222-4222-8222-222222222222',
  eventTime: '2026-09-25T02:00:00.000Z',
  magnitude: 4.2, latitude: 7.1, longitude: 125.6, depthKm: 12,
  locationDescription: 'Davao', origin: 'TECTONIC', sourceUrl: 'https://example.org/bulletin',
  forecast: null,
  forecastAvailability: { status: 'unavailable', reason: 'unknown' },
};

async function withServer(reader: EarthquakeReader, run: (base: string) => Promise<void>,
  simulations?: SimulationDependencies, now = () => new Date('2026-09-27T00:00:00Z')): Promise<void> {
  const server: Server = createApp(reader, now, undefined, undefined, undefined, simulations).listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('No test address');
  try { await run(`http://127.0.0.1:${address.port}`); }
  finally { server.closeAllConnections(); await new Promise<void>((resolve) => server.close(() => resolve())); }
}

test('simulation confirms the cookie server-side and validates requests before dispatch', async () => {
  const reader: EarthquakeReader = { search: async () => [], findById: async () => null, check: async () => {} };
  const cookies = new SimulationGuestCookies('1'.repeat(64));
  const pageToken = '2'.repeat(64);
  const ingressKey = '3'.repeat(64);
  let currentTime = Date.parse('2026-09-27T00:00:00.123Z');
  const catalogCutoff = '2026-09-26T12:00:00Z';
  const scenario = { latitude: 0, longitude: 135, magnitude: 1, depthKm: 700 };
  const runs: SimulationRequest[] = [];
  const dependencies: SimulationDependencies = {
    cookies, pageToken, ingressKey,
    simulator: {
      catalog: async () => ({ status: 'current', catalogCutoff }),
      run: async (request) => {
        runs.push(request);
        return { status: 429, retryAfter: 180, body: {
          error: { code: 'SIMULATION_LIMIT_REACHED', message: 'Simulation limit reached.', retryAt: '2026-09-27T00:03:00Z' },
        } };
      },
    },
  };
  await withServer(reader, async (base) => {
    const page = `${base}/internal/forecast-simulations/page`;
    const authorization = `Bearer ${pageToken}`;
    assert.equal((await fetch(page)).status, 404);
    const load = await fetch(page, { headers: { authorization } });
    assert.equal(load.status, 200);
    assert.equal(load.headers.get('cache-control'), 'no-store');
    const issued = load.headers.get('set-cookie');
    assert.ok(issued);
    for (const attribute of ['Max-Age=86400', 'Path=/', 'HttpOnly', 'Secure', 'SameSite=Lax']) {
      assert.ok(issued.includes(`; ${attribute}`));
    }
    assert.deepEqual(await load.json(), { guestCookieConfirmed: false, catalog: { status: 'current', catalogCutoff } });
    const cookie = issued.split(';')[0]!;
    const blocked = await fetch(`${page}?confirm=1`, { headers: { authorization } });
    assert.equal((await blocked.json() as { guestCookieConfirmed: boolean }).guestCookieConfirmed, false);
    assert.equal(blocked.headers.get('set-cookie'), null);
    const confirmed = await fetch(`${page}?confirm=1`, { headers: { authorization, cookie } });
    assert.equal((await confirmed.json() as { guestCookieConfirmed: boolean }).guestCookieConfirmed, true);
    assert.equal(confirmed.headers.get('set-cookie'), null);
    const runUrl = `${base}/api/v1/forecast-simulations`;
    assert.equal((await fetch(`${runUrl}/readiness`)).status, 404);
    const submit = (body: string, headers: Record<string, string> = {}) => fetch(runUrl, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body,
    });
    const noCookie = await submit(JSON.stringify(scenario));
    assert.equal(noCookie.status, 403);
    assert.equal(noCookie.headers.get('cache-control'), 'no-store');
    const malformed = await submit('{', { cookie });
    assert.equal(malformed.status, 400);
    assert.equal(malformed.headers.get('cache-control'), 'no-store');
    assert.equal((await submit(JSON.stringify(scenario), { cookie: `${cookie}a` })).status, 403);
    const invalidDepth = await submit(JSON.stringify({ ...scenario, depthKm: 700.1 }), { cookie });
    assert.equal(invalidDepth.status, 400);
    assert.equal((await invalidDepth.json() as { error: { field: string } }).error.field, 'depthKm');
    const untrusted = await submit(JSON.stringify(scenario), { cookie, 'CF-Connecting-IP': '203.0.113.7' });
    assert.equal(untrusted.status, 503);
    assert.equal(runs.length, 0);
    const admitted = await submit(JSON.stringify(scenario), {
      cookie, 'CF-Connecting-IP': '203.0.113.7', 'X-Simulation-Ingress': ingressKey,
    });
    assert.equal(admitted.status, 429);
    assert.equal(admitted.headers.get('retry-after'), '180');
    assert.equal(runs.length, 1);
    assert.equal(runs[0]?.clientIp, '203.0.113.7');
    assert.deepEqual(runs[0]?.scenario, scenario);
    currentTime += guestCookieLifetimeMs - 1;
    assert.ok(cookies.identify(cookie, new Date(currentTime)));
    currentTime += 1;
    assert.equal((await submit(JSON.stringify(scenario), { cookie })).status, 403);
  }, dependencies, () => new Date(currentTime));
});

test('search returns a bounded page and detail keeps missing forecast explicit', async () => {
  const reader: EarthquakeReader = {
    search: async () => [event, { ...event, eventId: '33333333-3333-4333-8333-333333333333' }],
    findById: async () => event,
    check: async () => {},
  };
  await withServer(reader, async (base) => {
    const search = await fetch(`${base}/api/v1/earthquakes/search`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ limit: 1 }),
    });
    assert.equal(search.status, 200);
    const page = await search.json() as { items: Array<{ forecast: unknown }>; hasMore: boolean; nextCursor: string };
    assert.equal(page.items.length, 1);
    assert.equal(page.items[0]?.forecast, null);
    assert.equal('forecastAvailability' in page.items[0]!, false, 'Availability is detail-only');
    assert.equal(page.hasMore, true);
    assert.ok(page.nextCursor);
    assert.ok(search.headers.get('x-request-id'));
    const detail = await fetch(`${base}/api/v1/earthquakes/${event.eventId}`);
    assert.equal(detail.status, 200);
    const data = await detail.json() as { item: { forecast: unknown; source: { provider: string }; forecastAvailability: unknown } };
    assert.equal(data.item.forecast, null);
    assert.equal(data.item.source.provider, 'PHIVOLCS');
    assert.deepEqual(data.item.forecastAvailability, { status: 'unavailable', reason: 'unknown' });
  });
});

test('forecast availability maps skip reasons and prioritizes prediction work', () => {
  for (const reason of ['history_coverage_unavailable', 'incomplete_feature_history',
    'history_starts_after_required_window', 'history_ends_before_anchor']) {
    assert.deepEqual(forecastAvailability(null, null, reason),
      { status: 'unavailable', reason: 'insufficient_history' });
  }
  assert.deepEqual(forecastAvailability(null, null, 'magnitude_below_m1'),
    { status: 'unavailable', reason: 'below_minimum_magnitude' });
  assert.deepEqual(forecastAvailability(null, null, 'model_release_unavailable'),
    { status: 'unavailable', reason: 'model_unavailable' });
  for (const reason of [null, 'unrecognized_reason']) {
    assert.deepEqual(forecastAvailability(null, null, reason), { status: 'unavailable', reason: 'unknown' });
  }
  for (const status of ['pending', 'running', 'retry_wait']) {
    assert.deepEqual(forecastAvailability(null, status, 'history_coverage_unavailable'),
      { status: 'processing', reason: null });
  }
  assert.deepEqual(forecastAvailability(null, 'failed', 'history_coverage_unavailable'),
    { status: 'failed', reason: null });
  for (const status of ['cancelled', 'succeeded']) {
    assert.deepEqual(forecastAvailability(null, status, 'history_coverage_unavailable'),
      { status: 'unavailable', reason: 'unknown' });
  }
});

test('invalid input and database outage return status and short messages', async () => {
  const reader: EarthquakeReader = {
    search: async () => { throw new DataUnavailable('private connection details'); },
    findById: async () => null,
    check: async () => {},
  };
  await withServer(reader, async (base) => {
    const bad = await fetch(`${base}/api/v1/earthquakes/search`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ limit: 0 }),
    });
    assert.equal(bad.status, 400);
    assert.match(JSON.stringify(await bad.json()), /INVALID_REQUEST/);
    const outage = await fetch(`${base}/api/v1/earthquakes/search`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}',
    });
    assert.equal(outage.status, 503);
    assert.doesNotMatch(JSON.stringify(await outage.json()), /private connection details/);
  });
});
