// Build first: pnpm build && pnpm test:forecast
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { loadObservationWindow } from '../src/lib/forecast-observations.ts';

process.env.ASTRO_NODE_AUTOSTART = 'disabled';
process.env.API_TARGET = 'http://forecast-fixture.invalid';
const eventId = '00000000-0000-4000-8000-000000000001';
const forecast = {
  forecastId: eventId, modelReleaseId: eventId,
  windowStart: '2026-10-01T00:00:00.000Z', windowEnd: '2026-10-02T00:00:00.000Z', expired: true,
  probabilityM1Plus24h: 0.8, probabilityM4Plus24h: 0.2, probabilityM5Plus24h: 0.1,
  expectedM1PlusCount24h: 2, activityRadiusMedianKm24h: 25,
  maximumMagnitudeQ05_24h: 1, maximumMagnitudeQ50_24h: 2, maximumMagnitudeQ95_24h: 4,
};
const event = {
  eventId, eventTime: forecast.windowStart, magnitude: 3, depthKm: 10,
  latitude: 13, longitude: 121, locationDescription: 'Test location',
  source: { provider: 'PHIVOLCS', url: 'https://earthquake.phivolcs.dost.gov.ph/' }, forecast,
};
let mode = 'normal', details = 0;
const searches = [];
const nativeFetch = globalThis.fetch;
const injection = '</script><script>window.injected=true</script>';
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input), 'http://forecast-fixture.invalid');
  assert.equal(url.hostname, 'forecast-fixture.invalid', 'Page data must use the configured Backend');
  if (!url.pathname.endsWith('/search')) {
    details++;
    if (mode === 'backend-error') return new Response(null, { status: 500 });
    if (mode === 'network-error') throw new TypeError('Network unavailable');
    if (mode === 'timeout') throw new DOMException('Timed out', 'TimeoutError');
    if (mode === 'detail-error') return new Response(null, { status: 404 });
    return Response.json({ item: {
      ...event, forecast: mode === 'no-forecast' ? null : forecast,
      locationDescription: mode === 'xss' ? injection : event.locationDescription,
    } });
  }
  const criteria = JSON.parse(init.body);
  searches.push(criteria);
  if (mode === 'blocked') throw new Error('Forecast HTML must not fetch observations');
  if (mode === 'bad-cursor') return Response.json({ items: [], hasMore: true, nextCursor: 'same' });
  if (mode === 'observations-error') return new Response(null, { status: 503 });
  if (!criteria.dateFrom || mode === 'empty') return Response.json({ items: [], hasMore: false, nextCursor: null });
  if (criteria.dateFrom === forecast.windowEnd) return Response.json({ items: [], hasMore: false, nextCursor: null });
  if (mode === 'paginated') {
    if (!criteria.cursor) return Response.json({ items: Array.from({ length: 100 }, (_, i) => ({
      ...event, eventId: String(i), eventTime: '2026-10-01T12:00:00.000Z',
    })), hasMore: true, nextCursor: 'next-page' });
    return Response.json({ items: [{ ...event, eventId: 'oldest', eventTime: '2026-10-01T01:00:00.000Z' }], hasMore: false, nextCursor: null });
  }
  return Response.json({ items: [event], hasMore: false, nextCursor: null });
};

const { handler } = await import('../dist/server/entry.mjs');
const server = createServer(handler);
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}`;
async function page(path = `/forecasts/${eventId}`, status = 200) {
  const response = await nativeFetch(base + path);
  assert.equal(response.status, status);
  return response.text();
}
function mapData(html) {
  return JSON.parse(html.match(/<script[^>]+id="activity-map-data"[^>]*>([\s\S]*?)<\/script>/)[1]);
}
try {
  mode = 'blocked';
  const html = await page();
  assert.match(html, /80%/);
  assert.match(html, /Loading observed earthquakes/);
  assert.equal(searches.length, 0, 'Forecast rendering must not wait for observation requests');
  mode = 'normal';
  assert.doesNotMatch(await page('/'), /<body class="forecast-page"/);
  const params = new URLSearchParams({ q: 'Test', date: 'custom', from: forecast.windowStart,
    to: forecast.windowEnd, magnitudes: 'mag-3' });
  const contextual = await page(`/forecasts/${eventId}?${params}`);
  assert.match(contextual, /class="forecast-back" href="\/\?q=Test&amp;date=custom/);
  assert.match(contextual, new RegExp(`selected=${eventId}`), 'The return link derives selection from the forecast path');
  const duplicate = await nativeFetch(`${base}/forecasts/${eventId}?${params}&selected=00000000-0000-4000-8000-000000000002`, { redirect: 'manual' });
  assert.equal(duplicate.status, 302);
  assert.equal(duplicate.headers.get('location'), `/forecasts/${eventId}?${params}`);
  searches.length = 0;
  await page(`/?${params}`);
  assert.deepEqual(searches[0], { limit: 30, location: 'Test', dateFrom: forecast.windowStart,
    dateTo: forecast.windowEnd, magnitudeRanges: [{ from: 3, below: 4 }] });
  const legacy = await nativeFetch(`${base}/?earthquake=${eventId}&${params}&selected=${eventId}`, { redirect: 'manual' });
  assert.equal(legacy.status, 302);
  assert.equal(legacy.headers.get('location'), `/forecasts/${eventId}?${params}`);
  assert.equal((await nativeFetch(`${base}/?earthquake=`, { redirect: 'manual' })).headers.get('location'), '/');
  const before = details;
  assert.match(await page('/forecasts/not-a-uuid', 400), /earthquake link is invalid/);
  assert.equal(details, before, 'Invalid IDs must not reach the Backend');
  mode = 'detail-error';
  assert.match(await page(undefined, 404), /earthquake was not found/);
  for (mode of ['backend-error', 'network-error', 'timeout']) {
    assert.match(await page(undefined, 503), /service is temporarily unavailable/);
  }
  mode = 'no-forecast';
  const noForecast = await page();
  assert.match(noForecast, /Forecast details are not available/);
  assert.doesNotMatch(noForecast, /data-activity-range/);
  mode = 'xss';
  const safe = await page();
  assert.doesNotMatch(safe, /<script>window\.injected=true<\/script>/);
  assert.equal(mapData(safe).anchor.location, injection);

  mode = 'paginated'; searches.length = 0;
  const observations = await loadObservationWindow(forecast.windowStart, forecast.windowEnd);
  assert.equal(observations.length, 101);
  assert.equal(observations[0].eventId, 'oldest');
  assert.deepEqual(searches[1], { limit: 100, dateFrom: forecast.windowStart, dateTo: forecast.windowEnd, cursor: 'next-page' });
  mode = 'empty';
  assert.deepEqual(await loadObservationWindow(forecast.windowStart, forecast.windowEnd), []);
  mode = 'observations-error';
  await assert.rejects(loadObservationWindow(forecast.windowStart, forecast.windowEnd), /unavailable/);
  mode = 'bad-cursor';
  await assert.rejects(loadObservationWindow(forecast.windowStart, forecast.windowEnd), /cursor/);
  console.log('Forecast routes, HTTP statuses, return context, deferred observations, pagination, and JSON escaping passed.');
} finally {
  globalThis.fetch = nativeFetch;
  await new Promise(resolve => server.close(resolve));
}
