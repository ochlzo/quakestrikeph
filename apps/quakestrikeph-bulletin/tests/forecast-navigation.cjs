// Build first. Requires Playwright and Microsoft Edge; all API data uses a local fixture.
const assert = require('node:assert/strict');
const { createServer } = require('node:http');
const { chromium } = require('playwright');

const eventId = '00000000-0000-4000-8000-000000000001';
const forecast = {
  forecastId: eventId, modelReleaseId: eventId,
  windowStart: '2026-10-01T00:00:00.000Z', windowEnd: '2026-10-02T00:00:00.000Z', expired: true,
  probabilityM1Plus24h: 0.8, probabilityM4Plus24h: 0.2, probabilityM5Plus24h: 0.1,
  expectedM1PlusCount24h: 2, activityRadiusMedianKm24h: 25,
  maximumMagnitudeQ05_24h: 1, maximumMagnitudeQ50_24h: 2, maximumMagnitudeQ95_24h: 4,
};
const event = {
  eventId, eventTime: forecast.windowStart, magnitude: 3.5, depthKm: 10,
  latitude: 13, longitude: 121, locationDescription: 'Test location',
  source: { provider: 'PHIVOLCS', url: 'https://earthquake.phivolcs.dost.gov.ph/' }, forecast,
};
const other = { ...event, eventId: '00000000-0000-4000-8000-000000000002',
  eventTime: '2026-10-01T01:00:00.000Z', locationDescription: 'Test other location' };
let mode = 'normal', holdObservations = false, releaseObservations = [], handler;
const searches = [];
const errors = [];
const mapStyle = {
  version: 8,
  sources: { fixture: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } } },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#eef4f4' } },
    { id: 'water', type: 'fill', source: 'fixture', paint: { 'fill-color': '#eef4f4' } },
  ],
};
function release() {
  holdObservations = false;
  releaseObservations.splice(0).forEach(resolve => resolve());
}

(async () => {
  const server = createServer(async (request, response) => {
    if (!request.url.startsWith('/api/v1/earthquakes')) return handler(request, response);
    response.setHeader('Content-Type', 'application/json');
    if (request.method === 'GET') return response.end(JSON.stringify({ item: event }));
    let raw = '';
    for await (const part of request) raw += part;
    const criteria = JSON.parse(raw);
    searches.push(criteria);
    const observation = criteria.limit === 100;
    if (observation && holdObservations) await new Promise(resolve => releaseObservations.push(resolve));
    if (observation && mode === 'error') { response.statusCode = 503; return response.end('{}'); }
    if (observation && mode === 'partial' && criteria.dateFrom === forecast.windowStart) {
      response.statusCode = 503; return response.end('{}');
    }
    let items = [event, other];
    if (!observation && mode === 'older-selection') items = [other];
    if (observation && mode === 'empty') items = [];
    if (observation && criteria.dateFrom === forecast.windowEnd) items = [];
    if (criteria.location) items = items.filter(item => item.locationDescription.toLowerCase().includes(criteria.location.toLowerCase()));
    if (criteria.dateFrom) items = items.filter(item => item.eventTime >= criteria.dateFrom);
    if (criteria.dateTo) items = items.filter(item => item.eventTime < criteria.dateTo);
    if (criteria.magnitudeRanges) items = items.filter(item => criteria.magnitudeRanges.some(range =>
      item.magnitude >= (range.from ?? -Infinity) && item.magnitude < (range.below ?? Infinity)));
    if (mode === 'xss' && observation) items = items.map(item => ({ ...item,
      locationDescription: '</span><script>window.injected=true</script>' }));
    response.end(JSON.stringify({ items, hasMore: false, nextCursor: null, fetchedAt: forecast.windowEnd }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const root = `http://127.0.0.1:${server.address().port}`;
  process.env.ASTRO_NODE_AUTOSTART = 'disabled';
  process.env.API_TARGET = root;
  ({ handler } = await import('../dist/server/entry.mjs'));
  let browser;
  try {
    browser = await chromium.launch({ channel: 'msedge', headless: true,
      args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
      page.on('pageerror', error => errors.push(error.stack));
      await page.route('https://tiles.openfreemap.org/**', route => route.fulfill({ json: mapStyle }));
      const params = new URLSearchParams({ q: 'Test', date: 'custom', from: '2026-09-30T16:00:00.000Z',
        to: '2026-10-02T16:00:00.000Z', magnitudes: 'mag-3', selected: eventId });
      const listUrl = `${root}/?${params}`;
      async function openDrawer() {
        if (viewport.width < 760 && !await page.getByRole('button', { name: 'Close earthquakes', exact: true }).isVisible()) {
          await page.getByRole('button', { name: 'Show earthquakes', exact: true }).click();
        }
      }
      async function checkRestored() {
        await page.waitForFunction(() => document.querySelectorAll('astro-island[ssr]').length === 0);
        await openDrawer();
        await page.locator('.selected-card').waitFor();
        assert.equal(await page.getByRole('textbox', { name: 'Search by location' }).inputValue(), 'Test');
        assert.match(await page.locator('.date-filter-trigger').textContent(), /Oct 1.*Oct 2/);
        assert.match(await page.locator('[data-slot="combobox-chip"]').textContent(), /M3.0/);
        const url = new URL(page.url());
        assert.equal(url.searchParams.get('selected'), eventId);
        assert.equal(url.searchParams.get('from'), params.get('from'));
        assert.equal(url.searchParams.get('to'), params.get('to'));
      }
      await page.goto(listUrl);
      await checkRestored();
      holdObservations = true;
      await page.getByRole('link', { name: 'View forecast' }).click();
      await page.locator('.forecast-page').waitFor();
      assert.equal(new URL(page.url()).pathname, `/forecasts/${eventId}`);
      assert.equal(new URL(page.url()).searchParams.has('selected'), false);
      assert.match(await page.locator('#forecast-panel-activity').textContent(), /80%/);
      assert.equal(await page.locator('.timeline-event-list').getAttribute('aria-busy'), 'true');
      assert.equal(await page.locator('[data-activity-play]').isDisabled(), true);
      release();
      await page.waitForFunction(() => document.querySelector('.timeline-event-list')?.getAttribute('aria-busy') === 'false');
      assert.equal(await page.locator('.timeline-event-row').count(), 2);
      await page.waitForFunction(() => !document.querySelector('[data-activity-range]')?.disabled);
      assert.equal(await page.locator('.activity-marker-anchor').count(), 1);
      assert.equal(await page.locator('.activity-marker-forecast').count(), 1, 'The anchor must not appear as another replay marker');
      await page.getByRole('link', { name: 'Back to earthquakes', exact: true }).click();
      await checkRestored();
      await page.reload();
      await checkRestored();
      await page.getByRole('link', { name: 'View forecast' }).click();
      await page.locator('.forecast-page').waitFor();
      assert.equal(new URL(page.url()).searchParams.has('selected'), false);
      await page.goBack();
      await checkRestored();
      mode = 'older-selection';
      await page.goto(listUrl);
      await checkRestored();
      assert.match(await page.locator('.selected-card').textContent(), /Test location/);
      mode = 'normal';
      await page.getByRole('textbox', { name: 'Search by location' }).fill('No matching location');
      await page.waitForFunction(() => !new URL(location.href).searchParams.has('selected'));
      await page.close();
    }
    const page = await browser.newPage();
    await page.route('https://tiles.openfreemap.org/**', route => route.fulfill({ json: mapStyle }));
    page.on('pageerror', error => errors.push(error.stack));
    for (mode of ['partial', 'error', 'empty', 'xss']) {
      await page.goto(`${root}/forecasts/${eventId}`);
      await page.waitForFunction(() => document.querySelector('.timeline-event-list')?.getAttribute('aria-busy') === 'false');
      const text = await page.locator('.timeline-event-list').textContent();
      if (mode === 'partial' || mode === 'error') {
        assert.match(text, /could not be loaded/);
        await page.locator('[data-observations-warning]').waitFor({ state: 'visible' });
        assert.equal(await page.locator('[data-observations-note]').isVisible(), false);
        assert.match(await page.locator('#forecast-panel-activity').textContent(), /80%/);
      } else if (mode === 'empty') assert.match(text, /No observed earthquakes/);
      else {
        assert.match(text, /<script>window.injected=true<\/script>/);
        assert.equal(await page.evaluate(() => window.injected), undefined);
      }
    }
    await page.close();
    assert.deepEqual(errors, []);
    console.log('Desktop/mobile forecast navigation, refresh, Back, older selection, delayed observations, partial failures, and safe rendering passed.');
  } finally {
    release();
    await browser?.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
