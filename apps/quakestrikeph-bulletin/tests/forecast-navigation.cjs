// Build first. Requires Playwright and Microsoft Edge; all API data uses a local fixture.
const assert = require('node:assert/strict');
const { createServer } = require('node:http');
const { mkdirSync } = require('node:fs');
const { resolve } = require('node:path');
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
  latitude: 13.1, longitude: 121.12,
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
    if (observation && mode === 'partial' && criteria.dateFrom === forecast.windowEnd) {
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
    for (const viewport of [{ width: 1440, height: 900 }, { width: 384, height: 844 }, { width: 320, height: 844 }]) {
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
      async function checkUnfiltered() {
        await page.waitForFunction(() => document.querySelectorAll('astro-island[ssr]').length === 0);
        await openDrawer();
        await page.locator('.selected-card').waitFor();
        assert.equal(await page.getByRole('textbox', { name: 'Search by location' }).inputValue(), '');
        assert.match(await page.locator('.date-filter-trigger').textContent(), /All dates/);
        assert.equal(await page.locator('[data-slot="combobox-chip"]').count(), 0);
        assert.equal(new URL(page.url()).search, `?selected=${eventId}`);
      }
      await page.goto(listUrl);
      await checkRestored();
      holdObservations = true;
      assert.equal(await page.getByRole('link', { name: 'View forecast' }).getAttribute('href'), `/forecasts/${eventId}`);
      await page.getByRole('link', { name: 'View forecast' }).click();
      await page.locator('.forecast-page').waitFor();
      assert.equal(new URL(page.url()).pathname, `/forecasts/${eventId}`);
      assert.equal(new URL(page.url()).search, '');
      assert.match(await page.locator('#forecast-panel-activity').textContent(), /80%/);
      assert.equal(await page.locator('.earthquake-timeline').count(), 0);
      assert.equal(await page.locator('[data-activity-play]').isDisabled(), true);
      release();
      await page.waitForFunction(() => !document.querySelector('[data-activity-play]')?.disabled);
      await page.locator('.maplibregl-canvas').waitFor();
      assert.ok(await page.locator('.map-panel').evaluate(element => element.clientHeight >= 300));
      assert.equal(await page.getByRole('button', { name: 'Zoom in', exact: true }).count(), 1);
      assert.equal(await page.getByRole('button', { name: 'Zoom out', exact: true }).count(), 1);
      assert.equal(await page.getByRole('button', { name: 'Recenter on trigger earthquake', exact: true }).count(), 1);
      assert.equal(await page.getByRole('button', { name: 'Show the Philippines', exact: true }).count(), 0);
      await page.waitForFunction(() => !document.querySelector('.terrain-button')?.disabled);
      assert.equal(await page.getByRole('button', { name: '3D terrain', exact: true }).getAttribute('aria-pressed'), 'false', 'Forecast maps start in 2D');
      await page.getByRole('button', { name: '3D terrain', exact: true }).click();
      assert.equal(await page.getByRole('button', { name: '3D terrain', exact: true }).getAttribute('aria-pressed'), 'true');
      await page.getByRole('button', { name: '3D terrain', exact: true }).click();
      assert.equal(await page.getByRole('button', { name: '3D terrain', exact: true }).getAttribute('aria-pressed'), 'false');
      if (viewport.width < 760) {
      const legend = page.getByRole('button', { name: 'Magnitude legend', exact: true });
      const legendWasOpen = await legend.getAttribute('aria-expanded');
      await legend.click();
      assert.equal(await legend.getAttribute('aria-expanded'), String(legendWasOpen !== 'true'));
      await legend.click();
      assert.equal(await legend.getAttribute('aria-expanded'), legendWasOpen);
      }
      assert.equal(await page.locator('.maplibregl-ctrl-attrib').count(), 1);
      assert.equal(await page.locator('.period-summary, #period-start, #observation-count').count(), 0, 'The replay summary is removed');
      await page.waitForFunction(() => document.querySelectorAll('.quake-marker').length === 1);
      const rangeStartHandle = page.locator('#history-handle');
      assert.equal(await page.locator('#include-history').count(), 0);
      assert.equal(await rangeStartHandle.isVisible(), true, 'The observation range start is always available');
      assert.equal(await rangeStartHandle.evaluate(el => el.style.transform), await page.locator('#replay-handle').evaluate(el => el.style.transform), 'Both handles start at the same time');
      await page.locator('#replay-handle').press('ArrowLeft');
      assert.match(await page.locator('#replay-handle').getAttribute('aria-label'), /08:00/, 'Replay cannot cross the range start');
      await rangeStartHandle.press('ArrowLeft');
      await page.locator('#replay-handle').press('ArrowLeft');
      assert.match(await page.locator('#replay-handle').getAttribute('aria-label'), /07:45/, 'Moving the range start allows replay before the trigger');
      assert.equal(await rangeStartHandle.evaluate(el => el.style.transform), await page.locator('#replay-handle').evaluate(el => el.style.transform), 'The handles can share the same time');
      await page.getByRole('button', { name: 'Restart at forecast start', exact: true }).click();
      await page.locator('#replay-handle').press('Shift+ArrowRight');
      await page.waitForFunction(() => document.querySelectorAll('.quake-marker').length === 2);
      assert.equal(await page.locator('.quake-marker.mag-3').count(), 2, 'Replay uses the Bulletin magnitude colors');
      const triggerPin = page.getByRole('button', { name: /Magnitude 3.5,.*Test location$/ });
      const observationPin = page.getByRole('button', { name: /Magnitude 3.5,.*Test other location$/ });
      const popup = page.locator('.forecast-observation-popup');
      const markerDistance = () => page.locator('.quake-marker').evaluateAll(pins => {
        const [a, b] = pins.map(pin => pin.getBoundingClientRect());
        return Math.hypot(a.x + a.width / 2 - b.x - b.width / 2, a.y + a.height / 2 - b.y - b.height / 2);
      });
      const originalDistance = await markerDistance();
      const originalPinWidth = await observationPin.evaluate(pin => pin.getBoundingClientRect().width);
      await observationPin.click();
      await popup.waitFor();
      assert.equal(await popup.locator('strong').textContent(), 'M3.5');
      assert.equal(await popup.locator('.forecast-observation-info span').nth(0).textContent(), '17 km from the trigger epicenter');
      assert.equal(await popup.locator('.forecast-observation-info span').nth(1).textContent(), 'Occurred 1 hour after the trigger earthquake');
      const popupLines = await popup.locator('.forecast-observation-info').evaluate(info =>
        [...info.children].map(line => line.getBoundingClientRect().top));
      assert.ok(popupLines[1] > popupLines[0] && popupLines[2] > popupLines[1], 'Magnitude, distance, and occurrence use separate lines');
      assert.equal(await page.locator('.quake-marker.is-selected').count(), 1);
      assert.ok(await triggerPin.evaluate(pin => pin.classList.contains('is-selected')), 'The trigger quake stays selected');
      assert.equal(await observationPin.evaluate(pin => pin.classList.contains('is-selected')), false);
      assert.equal(await observationPin.evaluate(pin => pin.getBoundingClientRect().width), originalPinWidth, 'Inspection preserves pin size');
      assert.ok(Math.abs(await markerDistance() - originalDistance) < 1, 'Inspection preserves zoom');
      const mapCenter = await page.locator('.map-canvas').boundingBox();
      const focusedPin = await observationPin.boundingBox();
      assert.ok(Math.abs(focusedPin.x + focusedPin.width / 2 - mapCenter.x - mapCenter.width / 2) < 2, 'Inspection centers the clicked pin horizontally');
      assert.ok(Math.abs(focusedPin.y + focusedPin.height / 2 - mapCenter.y - mapCenter.height / 2) < 2, 'Inspection centers the clicked pin vertically');
      const imageDirForPopup = resolve('../../.impeccable/review');
      mkdirSync(imageDirForPopup, { recursive: true });
      for (const close of await page.getByRole('button', { name: 'Close toast', exact: true }).all()) await close.click();
      await page.locator('.map-panel').screenshot({ path: resolve(imageDirForPopup, 'forecast-popup-' + viewport.width + '.png') });
      await popup.getByRole('button', { name: 'Close popup', exact: true }).click();
      assert.equal(await popup.count(), 0);
      assert.ok(await observationPin.evaluate(pin => pin === document.activeElement), 'Closing returns focus to the inspected pin');
      await observationPin.press('Enter');
      await popup.waitFor();
      await popup.getByRole('button', { name: 'Close popup', exact: true }).press('Escape');
      assert.equal(await popup.count(), 0);
      await observationPin.press('Enter');
      await popup.waitFor();
      await page.locator('.maplibregl-canvas').click({ position: { x: 30, y: 170 } });
      assert.equal(await popup.count(), 0, 'Clicking the map dismisses the popup');
      await observationPin.click();
      await popup.waitFor();
      await page.getByRole('button', { name: 'Recenter on trigger earthquake', exact: true }).click();
      assert.equal(await popup.count(), 0, 'Recentering dismisses pin inspection');
      const recenteredPin = await triggerPin.boundingBox();
      const recenteredMap = await page.locator('.map-canvas').boundingBox();
      assert.ok(Math.abs(recenteredPin.x + recenteredPin.width / 2 - recenteredMap.x - recenteredMap.width / 2) < 2, 'Recenter returns to the trigger longitude');
      assert.ok(Math.abs(recenteredPin.y + recenteredPin.height / 2 - recenteredMap.y - recenteredMap.height / 2) < 2, 'Recenter returns to the trigger latitude');
      assert.ok(Math.abs(await markerDistance() - originalDistance) < 1, 'Recenter preserves zoom');
      await observationPin.click();
      await popup.waitFor();
      await triggerPin.press('Enter');
      assert.equal(await popup.count(), 0, 'Activating the trigger dismisses inspection even when its pin is behind the popup');
      await observationPin.click();
      await popup.waitFor();
      await page.getByRole('button', { name: 'Restart at forecast start', exact: true }).click();
      await page.waitForFunction(() => document.querySelectorAll('.quake-marker').length === 1);
      assert.equal(await popup.count(), 0, 'Replay removes the popup with its observation');
      await page.locator('#replay-handle').press('Shift+ArrowRight');
      await page.waitForFunction(() => document.querySelectorAll('.quake-marker').length === 2);
      const requestCount = searches.filter(criteria => criteria.limit === 100).length;
      await page.getByRole('button', { name: 'Play replay', exact: true }).click();
      assert.equal(await page.locator('#pause-icon .lucide-pause').getAttribute('fill'), 'currentColor', 'The imported pause icon is filled');
      await page.getByRole('button', { name: 'Pause replay', exact: true }).click();
      assert.equal(await page.locator('#play-icon .lucide-play').count(), 1);
      assert.equal(await page.locator('#reset .lucide-rotate-ccw').count(), 1);
      assert.equal(searches.filter(criteria => criteria.limit === 100).length, requestCount, 'Play within cached time does not fetch');
      assert.equal(await page.locator('#play-icon').isVisible(), true);
      await page.getByRole('tab', { name: 'Magnitude', exact: true }).click();
      assert.match(await page.locator('#forecast-panel-magnitude').textContent(), /Lower estimate.*M1\.0.*Middle estimate.*M2\.0.*Upper estimate.*M4\.0/s);
      await page.getByRole('tab', { name: 'Magnitude', exact: true }).press('ArrowLeft');
      assert.equal(await page.getByRole('tab', { name: 'Chance and count', exact: true }).getAttribute('aria-selected'), 'true');
      await page.getByRole('button', { name: 'Magnitude 1.0 or higher', exact: false }).click();
      await page.getByRole('button', { name: 'Magnitude 4.0 or higher', exact: false }).click();
      assert.equal(await page.locator('#explain-m1').isVisible(), false);
      assert.equal(await page.locator('#explain-m4').isVisible(), true);
      await page.locator('.supporting-estimates summary').first().click();
      assert.equal(await page.locator('#explain-m4').isVisible(), true, 'Disclosure groups are independent');
      await rangeStartHandle.press('PageUp');
      await page.waitForFunction(() => document.querySelector('#replay-load-status')?.textContent === '');
      const cutoff = await page.locator('#history-handle').getAttribute('aria-label');
      await page.getByRole('button', { name: 'Play replay', exact: true }).click();
      await page.waitForFunction(() => document.querySelector('#replay-handle')?.getAttribute('aria-label')?.includes('09:06'));
      await page.getByRole('button', { name: 'Pause replay', exact: true }).click();
      assert.equal(await rangeStartHandle.getAttribute('aria-label'), cutoff, 'The observation range start stays fixed during playback');
      await page.getByRole('button', { name: 'Restart at forecast start', exact: true }).click();
      assert.equal(await rangeStartHandle.isVisible(), true);
      assert.match(await rangeStartHandle.getAttribute('aria-label'), /08:00/);
      assert.equal(await rangeStartHandle.evaluate(el => el.style.transform), await page.locator('#replay-handle').evaluate(el => el.style.transform), 'Reset returns both handles to the forecast start');
      assert.match(await page.locator('#replay-handle').getAttribute('aria-label'), /08:00/);
      await page.locator('#replay-handle').press('PageDown');
      await page.locator('#replay-handle').press('ArrowLeft');
      assert.match(await page.locator('#replay-handle').getAttribute('aria-label'), /07:45/);
      await page.getByRole('button', { name: 'Play replay', exact: true }).click();
      await page.waitForFunction(() => document.querySelector('#play')?.getAttribute('aria-pressed') === 'false');
      const stoppedAtEnd = await page.locator('#replay-handle').getAttribute('aria-label');
      assert.match(stoppedAtEnd, /Oct 2, 2026, 08:00/, 'Playback clamps the final step to the forecast end');
      assert.equal(await page.locator('#play-icon').isVisible(), true);
      assert.equal(await page.locator('#pause-icon').isVisible(), false);
      await page.waitForTimeout(250);
      assert.equal(await page.locator('#replay-handle').getAttribute('aria-label'), stoppedAtEnd, 'Playback stays paused at the end');
      await page.getByRole('button', { name: 'Play replay', exact: true }).click();
      assert.equal(await page.locator('#play').getAttribute('aria-pressed'), 'false', 'Playing at the end stays paused');
      await page.getByRole('button', { name: 'Restart at forecast start', exact: true }).click();
      await page.locator('#replay-handle').press('PageDown');
      await page.locator('#replay-handle').press('PageDown');
      await page.locator('#replay-handle').press('PageDown');
      assert.match(await page.locator('#replay-handle').getAttribute('aria-label'), /Oct 4/, 'Replay seeks beyond the previous 48-hour boundary');
      await page.getByRole('button', { name: 'Play replay', exact: true }).click();
      assert.equal(await page.locator('#play').getAttribute('aria-pressed'), 'false', 'Playing beyond the end stays paused');
      await page.getByRole('button', { name: 'Restart at forecast start', exact: true }).click();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'No horizontal page overflow');
      const imageDir = resolve('../../.impeccable/review');
      mkdirSync(imageDir, { recursive: true });
      for (const close of await page.getByRole('button', { name: 'Close toast', exact: true }).all()) await close.click();
      await page.locator('.probability[aria-expanded="true"]').click();
      await page.locator('.supporting-estimates details[open] summary').click();
      await page.evaluate(() => window.scrollTo(0, 0));
      const rulerSnapshot = () => page.locator('#time-viewport').evaluate(el => ({
        scrollLeft: el.scrollLeft, width: el.clientWidth,
        replayHidden: document.querySelector('#replay-handle').hidden,
        replayPosition: document.querySelector('#replay-handle').style.transform,
        rangeHidden: document.querySelector('#history-handle').hidden,
      }));
      const beforeScreenshot = await rulerSnapshot();
      await page.screenshot({ path: resolve(imageDir, 'forecast-' + viewport.width + '.png'), fullPage: true });
      assert.deepEqual(await rulerSnapshot(), beforeScreenshot, 'Resizing during screenshot capture preserves the visible time and both handles');
      await page.getByRole('link', { name: 'Back to earthquakes', exact: true }).click();
      await checkUnfiltered();
      await page.reload();
      await checkUnfiltered();
      await page.goto(listUrl);
      await checkRestored();
      await page.getByRole('link', { name: 'View forecast' }).click();
      await page.locator('.forecast-page').waitFor();
      assert.equal(new URL(page.url()).search, '');
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
    // Freeze Now inside the forecast window to exercise the future boundary.
    mode = 'normal';
    const now = '2026-10-01T01:07:00.000Z';
    const imageDir = resolve('../../.impeccable/review');
    for (const viewport of [{ width: 1440, height: 900 }, { width: 384, height: 844 }, { width: 320, height: 844 }]) {
      const page = await browser.newPage({ viewport, reducedMotion: 'reduce', hasTouch: viewport.width < 760 });
      page.on('pageerror', error => errors.push(error.stack));
      await page.clock.setFixedTime(new Date(now));
      await page.route('https://tiles.openfreemap.org/**', route => route.fulfill({ json: mapStyle }));
      await page.goto(root + '/forecasts/' + eventId);
      await page.waitForFunction(() => !document.querySelector('[data-activity-play]')?.disabled);
      const timeline = page.locator('#time-viewport');
      const handle = page.locator('#replay-handle');
      await handle.press('PageDown');
      assert.match(await handle.getAttribute('aria-label'), /Oct 1, 2026, 09:07/, 'Seek stops at the exact Now boundary without rounding into the future');
      assert.equal(await page.locator('#time-now').getAttribute('datetime'), now);
      assert.equal(await page.locator('#forecast-band span').isVisible(), false, 'A narrow forecast band does not show clipped text');
      assert.equal(await page.getByText('Future observations are not available', { exact: true }).isVisible(), true);
      assert.equal(await page.evaluate(() => {
        const boundary = parseFloat(document.querySelector('#time-future').style.left);
        return [...document.querySelectorAll('.ruler-tick')].every(tick => parseFloat(tick.style.left) <= boundary);
      }), true, 'No tick appears after Now');
      assert.match(await page.locator('.window-times').textContent(), /Oct 2, 2026, 08:00/, 'The full forecast end remains visible');
      await page.getByRole('button', { name: 'Play replay', exact: true }).click();
      assert.equal(await page.locator('#play').getAttribute('aria-pressed'), 'false', 'Playback stays paused at Now');
      await timeline.press('PageDown');
      const boundaryPosition = await timeline.evaluate(element => element.scrollLeft);
      await timeline.dispatchEvent('wheel', { deltaX: 600, deltaY: 0 });
      assert.equal(await timeline.evaluate(element => element.scrollLeft), boundaryPosition, 'Horizontal wheel stops at Now');
      await timeline.dispatchEvent('wheel', { deltaX: 0, deltaY: 600, shiftKey: true });
      assert.equal(await timeline.evaluate(element => element.scrollLeft), boundaryPosition, 'Shift-wheel stops at Now');
      assert.equal(await page.locator('#time-canvas').evaluate(element => element.style.transform), '', 'Reduced motion removes the stretch');
      const rect = await timeline.boundingBox();
      await page.mouse.move(rect.x + rect.width * 0.65, rect.y + 170);
      await page.mouse.down();
      await page.mouse.move(rect.x + 20, rect.y + 170, { steps: 4 });
      await page.mouse.up();
      assert.equal(await timeline.evaluate(element => element.scrollLeft), boundaryPosition, 'Drag panning stops at Now');
      const cursor = await handle.boundingBox();
      await page.mouse.move(cursor.x + cursor.width / 2, cursor.y + 12);
      await page.mouse.down();
      await page.mouse.move(rect.x + rect.width - 5, cursor.y + 12, { steps: 4 });
      await page.mouse.up();
      assert.match(await handle.getAttribute('aria-label'), /09:07/, 'Dragging the replay handle also stops at Now');
      if (viewport.width < 760) {
        const client = await page.context().newCDPSession(page);
        await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: rect.x + rect.width * 0.7, y: rect.y + 195 }] });
        await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: rect.x + 20, y: rect.y + 195 }] });
        await client.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
        assert.equal(await timeline.evaluate(element => element.scrollLeft), boundaryPosition, 'Touch panning stops at Now');
        await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: rect.x + 20, y: rect.y + 195 }] });
        await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: rect.x + 90, y: rect.y + 195 }] });
        await client.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
        assert.ok(await timeline.evaluate(element => element.scrollLeft) < boundaryPosition, 'Touch can still scroll into the past');
        await timeline.press('PageDown');
        await client.detach();
      }
      await page.emulateMedia({ reducedMotion: 'no-preference' });
      assert.match(await timeline.evaluate(element => {
        element.dispatchEvent(new WheelEvent('wheel', { deltaX: 600, cancelable: true }));
        return document.querySelector('#time-canvas').style.transform;
      }), /translateX\(-/, 'Scrolling past Now provides elastic feedback');
      await page.waitForFunction(() => !document.querySelector('#time-canvas').style.transform);
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await page.getByRole('button', { name: 'Restart at forecast start', exact: true }).click();
      await handle.press('Shift+ArrowRight');
      await page.getByRole('button', { name: 'Play replay', exact: true }).click();
      await page.waitForFunction(() => document.querySelector('#play')?.getAttribute('aria-pressed') === 'false');
      assert.match(await handle.getAttribute('aria-label'), /09:07/, 'Playback stops at Now inside an active forecast');
      assert.equal(await page.locator('.quake-marker').count(), 2, 'Available observations remain visible at Now');
      await page.getByRole('button', { name: 'Restart at forecast start', exact: true }).click();
      assert.match(await handle.getAttribute('aria-label'), /08:00/, 'Reset returns to the anchor');
      await handle.press('PageDown');
      assert.match(await handle.getAttribute('aria-label'), /09:07/, 'The observation range ends at Now');
      await page.locator('#history-handle').press('PageDown');
      assert.match(await page.locator('#history-handle').getAttribute('aria-label'), /09:07/, 'The range start can meet the replay time at Now');
      await page.locator('#history-handle').press('PageDown');
      assert.match(await page.locator('#history-handle').getAttribute('aria-label'), /09:07/, 'The range start cannot pass the replay time');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      for (const close of await page.getByRole('button', { name: 'Close toast', exact: true }).all()) await close.click();
      await timeline.screenshot({ path: resolve(imageDir, 'forecast-now-' + viewport.width + '.png') });
      await page.close();
    }
    const page = await browser.newPage();
    await page.route('https://tiles.openfreemap.org/**', route => route.fulfill({ json: mapStyle }));
    page.on('pageerror', error => errors.push(error.stack));
    for (mode of ['partial', 'error', 'empty', 'xss']) {
      await page.goto(root + '/forecasts/' + eventId);
      await page.waitForFunction(() => !document.querySelector('[data-activity-play]')?.disabled);
      if (mode === 'partial') {
        await page.waitForFunction(() => document.querySelector('#replay-load-status')?.textContent === '');
        await page.locator('#replay-handle').press('PageDown');
      }
      if (mode === 'partial' || mode === 'error') {
        await page.getByText('Observed earthquakes could not be loaded.', { exact: true }).waitFor();
        assert.match(await page.locator('#forecast-panel-activity').textContent(), /80%/);
        assert.equal(await page.getByRole('button', { name: 'Pause replay', exact: true }).count(), 0);
        await page.waitForFunction(expected => document.querySelectorAll('.quake-marker').length === expected, mode === 'partial' ? 2 : 1);
        mode = 'normal';
        await page.getByRole('button', { name: 'Retry', exact: true }).click();
        await page.waitForFunction(() => document.querySelector('#replay-load-status')?.textContent === '');
      } else {
        await page.locator('#replay-handle').press('Shift+ArrowRight');
        if (mode === 'empty') await page.waitForFunction(() => document.querySelectorAll('.quake-marker').length === 1);
        if (mode === 'xss') {
          await page.waitForFunction(() => document.querySelectorAll('.quake-marker').length === 2);
          assert.match(await page.locator('.quake-marker').last().getAttribute('aria-label'), /<script>window.injected=true<\/script>/);
          assert.equal(await page.evaluate(() => window.injected), undefined);
        }
      }
    }
    await page.close();
    assert.deepEqual(errors, []);
    console.log('Desktop/mobile forecast navigation, Now boundary, wheel/touch/keyboard, reduced motion, playback, delayed observations, failures, and safe rendering passed.');
  } finally {
    release();
    await browser?.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
