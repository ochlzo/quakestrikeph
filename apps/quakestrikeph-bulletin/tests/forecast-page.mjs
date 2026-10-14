// Build first: pnpm build && pnpm test:forecast
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { ForecastObservationCache } from '../src/lib/forecast-observation-cache.ts';
import { loadObservationWindow } from '../src/lib/api/forecast-observations.ts';
import { occurrenceRelativeTo } from '../src/lib/events.ts';

const triggerTime = '2026-10-01T12:00:00.000Z';
for (const [time, expected] of [
  ['2026-10-02T00:00:00.000Z', 'Occurred 12 hours after the trigger earthquake'],
  ['2026-10-01T00:00:00.000Z', 'Occurred 12 hours before the trigger earthquake'],
  ['2026-10-01T13:00:00.000Z', 'Occurred 1 hour after the trigger earthquake'],
  ['2026-10-01T10:30:00.000Z', 'Occurred 1.5 hours before the trigger earthquake'],
  ['2026-10-01T12:15:00.000Z', 'Occurred 15 minutes after the trigger earthquake'],
  ['2026-10-01T11:59:00.000Z', 'Occurred 1 minute before the trigger earthquake'],
  ['2026-10-01T12:00:30.000Z', 'Occurred less than 1 minute after the trigger earthquake'],
  [triggerTime, 'Occurred at the same time as the trigger earthquake'],
  ['2026-10-01T20:00:00+08:00', 'Occurred at the same time as the trigger earthquake'],
]) assert.equal(occurrenceRelativeTo(time, triggerTime), expected);

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
let availabilityFixture;
const searches = [];
const nativeFetch = globalThis.fetch;
const injection = '</script><script>window.injected=true</script>';
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input), 'http://forecast-fixture.invalid');
  assert.equal(url.hostname, 'forecast-fixture.invalid', 'Page data must use the configured Backend');
  if (!url.pathname.endsWith('/search') && !url.pathname.endsWith('/observations')) {
    details++;
    if (mode === 'backend-error') return new Response(null, { status: 500 });
    if (mode === 'network-error') throw new TypeError('Network unavailable');
    if (mode === 'timeout') throw new DOMException('Timed out', 'TimeoutError');
    if (mode === 'detail-error') return new Response(null, { status: 404 });
    return Response.json({ ...(url.searchParams.get('test') === 'true' ? { expiresAt: new Date(Date.now() + 3600000).toISOString() } : {}), item: {
      ...event, forecast: mode === 'no-forecast' ? null : forecast,
      forecastAvailability: mode === 'no-forecast' ? availabilityFixture : { status: 'available', reason: null },
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

try {
  mode = 'blocked';
  const html = await page();
  assert.match(html, /80%/);
  assert.match(html, /Loading observations/);
  assert.match(html, /<section[^>]*data-forecast-replay/);
  assert.match(html, /id="time-viewport"/);
  assert.match(html, /id="play"[^>]*disabled/);
  assert.match(html, /Enable JavaScript to use the map and replay/);
  assert.doesNotMatch(html, /data-timeline-root|timeline-event-list|What appeared during this window/);
  assert.doesNotMatch(html, /include-history|Start from previous earthquakes/);
  assert.match(html, /lucide-play/);
  assert.match(html, /lucide-pause/);
  assert.match(html, /lucide-rotate-ccw/);
  assert.equal(searches.length, 0, 'Forecast rendering must not wait for observation requests');
  mode = 'normal';
  const synthetic = await page(`/forecasts/${eventId}?test=true`);
  assert.match(synthetic, /class="forecast-back" href="\/"/);
  assert.match(synthetic, new RegExp(`data-synthetic-event="${eventId}"`));
  assert.match(synthetic, /https:\/\/earthquake.phivolcs.dost.gov.ph\//);
  assert.doesNotMatch(synthetic, /Test forecast|Synthetic forecast/);
  const canonicalTest = await nativeFetch(`${base}/forecasts/${eventId}?test=true&q=extra`, { redirect: 'manual' });
  assert.equal(canonicalTest.headers.get('location'), `/forecasts/${eventId}?test=true`);
  mode = 'backend-error';
  assert.match(await page(`/forecasts/${eventId}?test=true`, 503), new RegExp(`href="/forecasts/${eventId}\\?test=true"`));
  mode = 'detail-error';
  assert.match(await page(`/forecasts/${eventId}?test=true`, 404), /Invalid earthquake link/);
  mode = 'normal';
  const probabilityFields = ['probabilityM1Plus24h', 'probabilityM4Plus24h', 'probabilityM5Plus24h'];
  const originalProbabilities = probabilityFields.map(field => forecast[field]);
  for (const values of [[0.08, 0.01, 0.001], [0, 0, 0], [0.99, 0.99, 0.99]]) {
    probabilityFields.forEach((field, index) => { forecast[field] = values[index]; });
    const chart = (await page()).match(/<svg class="chance-chart"[\s\S]*?<\/svg>/)?.[0];
    assert.ok(chart);
    const frame = chart.match(/viewBox="([^"]+)"/)[1].split(' ').map(Number);
    const outer = chart.match(/<rect x="([^"]+)" y="([^"]+)" width="([^"]+)" height="([^"]+)"/).slice(1).map(Number);
    assert.equal(outer[0] - frame[0], 8, 'Small probabilities leave no unused space before the chart');
    assert.equal(outer[1] - frame[1], 8, 'Small probabilities stay aligned vertically');
    assert.equal(frame[2] - outer[2], 16, 'The viewport fits the visible boxes');
    assert.equal(frame[3] - outer[3], 16, 'The viewport preserves padding below the boxes');
    if (values[0] === 0.08) assert.match(chart, /8%[\s\S]*1%[\s\S]*&lt;1%/);
  }
  probabilityFields.forEach((field, index) => { forecast[field] = originalProbabilities[index]; });
  assert.doesNotMatch(await page('/'), /<body class="forecast-page"/);
  const params = new URLSearchParams({ q: 'Test', date: 'custom', from: forecast.windowStart,
    to: forecast.windowEnd, magnitudes: 'mag-3' });
  assert.match(html, new RegExp(`class="forecast-back" href="/\\?selected=${eventId}"`),
    'The return link selects the forecast event without Bulletin filters');
  const filtered = await nativeFetch(`${base}/forecasts/${eventId}?${params}`, { redirect: 'manual' });
  assert.equal(filtered.status, 302);
  assert.equal(filtered.headers.get('location'), `/forecasts/${eventId}`);
  const duplicate = await nativeFetch(`${base}/forecasts/${eventId}?${params}&selected=00000000-0000-4000-8000-000000000002`, { redirect: 'manual' });
  assert.equal(duplicate.status, 302);
  assert.equal(duplicate.headers.get('location'), `/forecasts/${eventId}`);
  searches.length = 0;
  await page(`/?${params}`);
  assert.deepEqual(searches[0], { limit: 30, location: 'Test', dateFrom: forecast.windowStart,
    dateTo: forecast.windowEnd, magnitudeRanges: [{ from: 3, below: 4 }] });
  const legacy = await nativeFetch(`${base}/?earthquake=${eventId}&${params}&selected=${eventId}`, { redirect: 'manual' });
  assert.equal(legacy.status, 302);
  assert.equal(legacy.headers.get('location'), `/forecasts/${eventId}`);
  assert.equal((await nativeFetch(`${base}/?earthquake=`, { redirect: 'manual' })).headers.get('location'), '/');
  const before = details;
  const invalid = await page('/forecasts/not-a-uuid', 400);
  assert.match(invalid, /earthquake link is invalid/);
  assert.match(invalid, /<h1 id="forecast-error-title">Invalid earthquake link<\/h1>/);
  assert.doesNotMatch(invalid, /Try again/);
  assert.equal(details, before, 'Invalid IDs must not reach the Backend');
  mode = 'detail-error';
  const missing = await page(undefined, 404);
  assert.match(missing, /earthquake was not found/);
  assert.match(missing, /<h1 id="forecast-error-title">Earthquake not found<\/h1>/);
  assert.doesNotMatch(missing, /Try again/);
  for (mode of ['backend-error', 'network-error', 'timeout']) {
    const failed = await page(undefined, 503);
    const errorState = failed.match(/<section aria-labelledby="forecast-error-title">([\s\S]*?)<\/section>/)?.[1];
    assert.ok(errorState, 'Page load failures must have a persistent error section');
    assert.match(errorState, /<h1 id="forecast-error-title">Forecast could not load<\/h1>/);
    assert.match(errorState, /<p>The earthquake service is temporarily unavailable\.<\/p>/);
    assert.match(errorState, /data-slot="empty"/);
    assert.match(errorState, /lucide-earth/);
    assert.match(errorState, new RegExp(`<a[^>]*href="/forecasts/${eventId}"[^>]*>Try again</a>`));
    assert.doesNotMatch(errorState, /astro-island|noscript/, 'The error and retry action must not need JavaScript');
  }
  mode = 'normal';
  assert.match(await page(), /80%/, 'Reloading the same route can recover after a transient failure');
  mode = 'no-forecast';
  const noForecast = await page();
  assert.match(noForecast, /Forecast unavailable/);
  assert.match(noForecast, /The reason is currently unavailable/);
  assert.match(noForecast, /View PHIVOLCS bulletin/);
  assert.match(noForecast, /An unavailable forecast does not mean further earthquake activity is unlikely/);
  assert.doesNotMatch(noForecast, /data-activity-range/);
  for (const [status, reason, title, explanation] of [
    ['unavailable', 'insufficient_history', 'Forecast unavailable', 'seven days before this earthquake'],
    ['unavailable', 'below_minimum_magnitude', 'Forecast unavailable', 'below that minimum'],
    ['unavailable', 'model_unavailable', 'Forecast unavailable', 'model was unavailable'],
    ['unavailable', 'unknown', 'Forecast unavailable', 'reason is currently unavailable'],
    ['processing', null, 'Forecast processing', 'system is preparing the forecast'],
    ['failed', null, 'Forecast could not be generated', 'could not complete forecast generation'],
  ]) {
    availabilityFixture = { status, reason };
    const availabilityHtml = await page();
    assert.match(availabilityHtml, new RegExp(title));
    assert.match(availabilityHtml, new RegExp(explanation));
    assert.equal(availabilityHtml.includes('Reload forecast page'), status === 'processing');
    assert.doesNotMatch(availabilityHtml, /data-activity-range|history_starts_after_required_window|insufficient_history/);
  }
  mode = 'xss';
  const safe = await page();
  assert.doesNotMatch(safe, /<script>window\.injected=true<\/script>/);
  assert.match(safe, /&lt;\/script&gt;/, 'Astro must escape the event passed to the React island');

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

  const origin = Date.parse(forecast.windowStart), day = 86400000;
  const calls = [];
  const cache = new ForecastObservationCache(origin, async (from, to) => {
    calls.push({ from, to });
    return [event, { ...event, eventId: 'boundary', eventTime: new Date(origin + day).toISOString() },
      { ...event, eventId: 'one-hour', eventTime: new Date(origin + 3600000).toISOString() }];
  });
  assert.equal(cache.covered(origin, origin), false);
  await Promise.all([cache.ensure(origin, origin + day - 1, origin + 3 * day),
    cache.ensure(origin, origin + 3600000, origin + 3 * day)]);
  assert.equal(calls.length, 1, 'Concurrent loads share one chunk request');
  assert.equal(cache.observations(origin, origin + 3599999, eventId).length, 0);
  assert.equal(cache.observations(origin, origin + 3600000, eventId).length, 1, 'Replay includes the exact observation instant');
  assert.equal(cache.covered(origin, origin + day), false, 'Exclusive search end requires the next chunk at the boundary');
  await cache.ensure(origin, origin + day, origin + 3 * day);
  assert.equal(calls.length, 2);
  assert.equal(cache.observations(origin, origin + day, eventId).length, 2, 'Duplicate IDs across chunks count once');
  await cache.ensure(origin, origin + day, origin + 3 * day);
  assert.equal(calls.length, 2, 'Cached playback does not issue new requests');
  await cache.ensure(origin + 4 * day, origin + 5 * day, origin + 3 * day);
  assert.equal(calls.length, 2, 'Future-only periods never fetch');
  const emptyCache = new ForecastObservationCache(origin, async () => []);
  await emptyCache.ensure(origin, origin, origin + day);
  assert.equal(emptyCache.covered(origin, origin), true, 'Loaded empty periods are distinct from pending periods');
  let failures = 0;
  const retryCache = new ForecastObservationCache(origin, async () => {
    if (++failures === 1) throw new Error('offline');
    return [];
  });
  await assert.rejects(retryCache.ensure(origin, origin, origin + day), /offline/);
  assert.equal(retryCache.covered(origin, origin), false);
  await retryCache.ensure(origin, origin, origin + day);
  assert.equal(retryCache.covered(origin, origin), true);
  const recentCalls = [];
  const recentCache = new ForecastObservationCache(origin, async (_from, to) => { recentCalls.push(to); return []; });
  await recentCache.ensure(origin, origin + day, origin + 1000);
  assert.equal(recentCalls[0], new Date(origin + 1001).toISOString(), 'Requests stop at the available time');
  await recentCache.ensure(origin, origin + day, origin + 2000);
  assert.equal(recentCalls.length, 2, 'A fresh play can extend a recently loaded chunk');

  let active = true, loads = 0;
  const staleCache = new ForecastObservationCache(origin, async () => { loads++; active = false; return []; });
  await staleCache.ensure(origin, origin + 3 * day, origin + 5 * day, () => active);
  assert.equal(loads, 1, 'A superseded selection does not continue loading older chunks');
  let releaseRecent;
  const concurrentCalls = [];
  const concurrentRecent = new ForecastObservationCache(origin, async (_from, to) => {
    concurrentCalls.push(to);
    if (concurrentCalls.length === 1) await new Promise(resolve => { releaseRecent = resolve; });
    return [];
  });
  const older = concurrentRecent.ensure(origin, origin + day, origin + 1000);
  const newer = concurrentRecent.ensure(origin, origin + day, origin + 2000);
  releaseRecent();
  await Promise.all([older, newer]);
  assert.equal(concurrentCalls.length, 2, 'A newer available cutoff extends an already pending chunk');
  assert.equal(concurrentRecent.covered(origin, origin + day, origin + 2000), true);
  console.log('Forecast routes, HTTP statuses, clean URLs, deferred observations, pagination, and JSON escaping passed.');
} finally {
  globalThis.fetch = nativeFetch;
  await new Promise(resolve => server.close(resolve));
}
