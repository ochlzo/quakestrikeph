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
      const page = await browser.newPage({ viewport, reducedMotion: 'reduce', hasTouch: viewport.width < 760 });
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
      await page.waitForFunction(() => !document.querySelector('.navigation astro-island[ssr]'));
      const navigation = page.getByRole('tablist', { name: 'Forecast sections' });
      assert.equal(await navigation.getAttribute('data-slot'), 'tabs-list');
      assert.equal(await navigation.getByRole('tab').count(), viewport.width < 760 ? 4 : 3);
      assert.equal(await navigation.getByRole('tab', { name: 'Activity map' }).isVisible(), viewport.width < 760);
      const detailsTab = navigation.getByRole('tab', { name: 'Forecast details' });
      await detailsTab.click();
      await page.waitForFunction(() => document.querySelector('.navigation [href="#forecast-details"]')?.getAttribute('aria-selected') === 'true');
      assert.equal(new URL(page.url()).hash, '#forecast-details');
      assert.equal(await page.locator('#main-facts').isVisible(), true, 'Tab navigation keeps every section rendered');
      assert.equal(await navigation.evaluate(element => {
        const selected = element.querySelector('[data-selected]').getBoundingClientRect();
        const list = element.getBoundingClientRect();
        const highlight = getComputedStyle(element, '::before');
        const shift = new DOMMatrixReadOnly(highlight.transform).m41;
        return Math.abs(list.left + parseFloat(highlight.left) + shift - selected.left) < 1
          && Math.abs(parseFloat(highlight.width) - selected.width) < 1
          && highlight.transitionDuration === '0s';
      }), true, 'The sliding highlight aligns with the active tab and respects reduced motion');
      await detailsTab.press('ArrowRight');
      await navigation.getByRole('tab', { name: 'Disclaimer' }).press('Enter');
      await page.waitForFunction(() => document.querySelector('.navigation [href="#disclaimer"]')?.getAttribute('aria-selected') === 'true');
      assert.equal(new URL(page.url()).hash, '#disclaimer');
      await page.locator('#main-facts').evaluate(element => element.scrollIntoView());
      await page.waitForFunction(() => document.querySelector('.navigation [href="#main-facts"]')?.getAttribute('aria-selected') === 'true');
      if (viewport.width < 760) {
        await navigation.getByRole('tab', { name: 'Activity map' }).click();
        await page.waitForFunction(() => document.querySelector('.navigation [href="#activity-map"]')?.getAttribute('aria-selected') === 'true');
      }
      await navigation.getByRole('tab', { name: 'Main facts' }).click();
      await page.waitForFunction(() => document.querySelector('.navigation [href="#main-facts"]')?.getAttribute('aria-selected') === 'true');
      await page.emulateMedia({ reducedMotion: 'no-preference' });
      await page.evaluate(() => {
        window.sectionSelections = [];
        new MutationObserver(() => {
          const selected = document.querySelector('.navigation [aria-selected="true"]');
          if (selected) window.sectionSelections.push(selected.getAttribute('href'));
        }).observe(document.querySelector('.navigation'), { subtree: true, attributes: true, attributeFilter: ['aria-selected'] });
      });
      async function waitForSection(id) {
        await page.waitForFunction(id => {
          const section = document.getElementById(id);
          const target = Math.max(0, Math.min(document.documentElement.scrollHeight - innerHeight,
            scrollY + section.getBoundingClientRect().top - parseFloat(getComputedStyle(section).scrollMarginTop)));
          return Math.abs(scrollY - target) < 1;
        }, id);
        await page.waitForTimeout(180);
      }
      const destinations = viewport.width < 760
        ? ['disclaimer', 'main-facts', 'forecast-details', 'activity-map', 'main-facts']
        : ['disclaimer', 'main-facts', 'forecast-details', 'main-facts'];
      for (const id of destinations) {
        await page.evaluate(() => { window.sectionSelections = []; });
        await navigation.locator(`[href="#${id}"]`).click();
        await waitForSection(id);
        assert.deepEqual(await page.evaluate(() => [...new Set(window.sectionSelections)]), [`#${id}`],
          `Smooth navigation to ${id} never selects intervening sections`);
      }
      await navigation.getByRole('tab', { name: 'Disclaimer' }).click();
      await page.waitForFunction(() => scrollY > 100 && document.querySelector('#forecast-details').getBoundingClientRect().top > 84);
      await page.evaluate(() => { window.sectionSelections = []; });
      await navigation.getByRole('tab', { name: 'Forecast details' }).click();
      await waitForSection('forecast-details');
      assert.deepEqual(await page.evaluate(() => [...new Set(window.sectionSelections)]), ['#forecast-details'], 'A repeated click replaces the scroll destination');
      await navigation.getByRole('tab', { name: 'Main facts' }).click();
      await waitForSection('main-facts');
      await navigation.getByRole('tab', { name: 'Disclaimer' }).press('Enter');
      await page.waitForFunction(() => scrollY > 100 && document.querySelector('#forecast-details').getBoundingClientRect().top > 84);
      if (viewport.width < 760) await page.touchscreen.tap(10, 200);
      else {
        await page.mouse.move(10, 200);
        await page.mouse.wheel(0, -200);
      }
      await page.waitForFunction(() => document.querySelector('.navigation [href="#disclaimer"]')?.getAttribute('aria-selected') === 'false');
      await navigation.getByRole('tab', { name: 'Main facts' }).click();
      await waitForSection('main-facts');
      await navigation.getByRole('tab', { name: 'Disclaimer' }).click();
      await page.waitForFunction(() => scrollY > 100 && document.querySelector('#forecast-details').getBoundingClientRect().top > 84);
      await page.keyboard.press('PageUp');
      await page.waitForFunction(() => document.querySelector('.navigation [href="#disclaimer"]')?.getAttribute('aria-selected') === 'false');
      await navigation.getByRole('tab', { name: 'Main facts' }).click();
      await waitForSection('main-facts');
      await navigation.getByRole('tab', { name: 'Main facts' }).click();
      await page.waitForTimeout(180);
      await page.locator('#forecast-details').evaluate(element => element.scrollIntoView({ behavior: 'instant' }));
      await page.waitForFunction(() => document.querySelector('.navigation [href="#forecast-details"]')?.getAttribute('aria-selected') === 'true');
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await navigation.getByRole('tab', { name: 'Main facts' }).click();
      await waitForSection('main-facts');
      assert.equal(await page.locator('#time-viewport').evaluate(element => {
        const band = document.querySelector('#forecast-band');
        const left = parseFloat(band.style.left) - element.scrollLeft;
        return Math.abs(left - 8) < 1 && Math.abs(element.clientWidth - left - parseFloat(band.style.width) - 8) < 1;
      }), true, 'The default view fits the forecast with 8px on each edge');
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
      assert.ok(await observationPin.evaluate(pin => pin === document.activeElement), 'Escape inside the popup returns focus to the inspected pin');
      for (const name of ['Zoom in', 'Zoom out']) {
        await observationPin.press('Enter');
        await popup.waitFor();
        const control = page.getByRole('button', { name, exact: true });
        await control.click();
        await control.press('Escape');
        assert.equal(await popup.count(), 0, 'Escape from ' + name + ' dismisses the popup');
        assert.ok(await control.evaluate(button => button === document.activeElement), 'Escape keeps focus on ' + name);
      }
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
      assert.equal(await page.locator('#forecast-details').getByRole('tab').count(), 0, 'Forecast explanations have no tabs');
      const explanations = page.locator('#forecast-details .explanation-section');
      assert.equal(await explanations.count(), 4, 'Chance, count, magnitude, and area have separate sections');
      for (const section of await explanations.all()) {
        assert.equal(await section.isVisible(), true, 'Every explanation is visible without selecting a tab');
        assert.equal(await section.locator('.panel-columns').evaluate(element =>
          getComputedStyle(element).gridTemplateColumns.split(' ').length), viewport.width > 760 ? 2 : 1,
        'Each section pairs its graphic and text on desktop and stacks them on mobile');
      }
      assert.match(await page.locator('#forecast-panel-magnitude .magnitude-ruler').getAttribute('aria-label'),
        /lower M1\.0, middle M2\.0, upper M4\.0/);
      const timeline = page.locator('#time-viewport');
      const zoom = page.locator('#timeline-zoom');
      assert.equal(await zoom.getAttribute('data-slot'), 'button', 'Timeline zoom uses the shared shadcn Button');
      assert.equal(await zoom.getAttribute('data-variant'), 'outline');
      assert.equal(await zoom.getAttribute('data-size'), 'default', 'The zoom button uses the shared text size');
      assert.equal(await page.locator('.replay-zoom').count(), 1, 'One view button replaces the three zoom controls');
      assert.equal(await zoom.textContent(), '24h view', 'The default zoom level is 2');
      const fit = async () => {
        for (let index = 0; index < 4; index++) {
          await zoom.click();
          if (await zoom.textContent() === '24h view') return;
        }
        assert.fail('The zoom cycle must return to level 2 within four clicks');
      };
      const geometry = () => timeline.evaluate(element => {
        const labels = [...document.querySelectorAll('.ruler-offset')].slice(0, 2);
        const hours = label => Number(label.textContent.replace('−', '-').replace('h', ''));
        const position = label => parseFloat(label.closest('.ruler-tick').style.left);
        return {
          width: element.clientWidth,
          hourWidth: (position(labels[1]) - position(labels[0])) / (hours(labels[1]) - hours(labels[0])),
          bandWidth: parseFloat(document.querySelector('#forecast-band').style.width),
          bandLeft: parseFloat(document.querySelector('#forecast-band').style.left) - element.scrollLeft,
          selected: parseFloat(document.querySelector('#replay-handle').style.transform.match(/translate3d\(([-\d.]+)/)[1]) + 22 - element.scrollLeft,
        };
      });
      await fit();
      const fitted = await geometry();
      assert.ok(Math.abs(fitted.bandLeft - 8) < 1, 'The forecast starts 8px from the ruler edge');
      assert.ok(Math.abs(fitted.width - fitted.bandLeft - fitted.bandWidth - 8) < 1, 'The forecast ends 8px from the ruler edge');
      const selectedTime = await page.locator('#replay-handle').getAttribute('aria-label');
      const rangeTime = await rangeStartHandle.getAttribute('aria-label');
      for (const [level, hours] of [[3, 48], [4, 96], [1, 6], [2, 24]]) {
        await zoom.click();
        assert.equal(await zoom.textContent(), `${hours}h view`, 'Clicking advances the level and wraps 4 to 1');
        assert.match(await zoom.getAttribute('aria-label'), new RegExp(`Timeline zoom, ${hours}h view`));
        assert.ok(Math.abs((await geometry()).hourWidth / fitted.hourWidth - 24 / hours) < 0.01);
        if (level !== 2) assert.ok(Math.abs((await geometry()).selected - fitted.selected) < 1, 'Button zoom keeps the selected time in place');
      }
      assert.ok(Math.abs((await geometry()).bandLeft - 8) < 1, 'Returning to level 2 fits the original forecast');
      assert.equal(await page.locator('#replay-handle').getAttribute('aria-label'), selectedTime);
      assert.equal(await rangeStartHandle.getAttribute('aria-label'), rangeTime);
      await fit();
      const rect = await timeline.boundingBox();
      for (let index = 0; index < 30; index++)
        await timeline.dispatchEvent('wheel', { ctrlKey: true, deltaY: -10, clientX: rect.x + rect.width / 2 });
      assert.ok((await geometry()).hourWidth > fitted.hourWidth, 'Ctrl-wheel zooms the ruler');
      assert.equal(await zoom.textContent(), '6h view', 'Small wheel deltas accumulate and update the view button');
      for (let index = 0; index < 4; index++)
        await timeline.dispatchEvent('wheel', { ctrlKey: true, deltaY: 1000, clientX: rect.x + rect.width / 2 });
      assert.equal(await zoom.textContent(), '96h view', 'Ctrl-wheel obeys the zoom-out limit');
      assert.ok(Math.abs((await geometry()).hourWidth / fitted.hourWidth - 0.25) < 0.01);
      for (let index = 0; index < 4; index++)
        await timeline.dispatchEvent('wheel', { ctrlKey: true, deltaY: -1000, clientX: rect.x + rect.width / 2 });
      assert.equal(await zoom.textContent(), '6h view', 'Ctrl-wheel obeys the zoom-in limit');
      assert.ok(Math.abs((await geometry()).hourWidth / fitted.hourWidth - 4) < 0.01);
      await fit();
      if (viewport.width < 760) {
        const client = await page.context().newCDPSession(page);
        const center = rect.x + rect.width / 2;
        const points = distance => [
          { id: 1, x: center - distance / 2, y: rect.y + 180 },
          { id: 2, x: center + distance / 2, y: rect.y + 180 },
        ];
        await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: points(80) });
        await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: points(240) });
        assert.equal(await zoom.textContent(), '6h view', 'Spreading two fingers selects level 1');
        assert.ok(Math.abs((await geometry()).hourWidth / fitted.hourWidth - 4) < 0.02, 'Spreading two fingers zooms in');
        await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: points(20) });
        assert.equal(await zoom.textContent(), '96h view', 'Pinching inward reaches level 4');
        assert.ok(Math.abs((await geometry()).hourWidth / fitted.hourWidth - 0.25) < 0.01);
        await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: points(300) });
        assert.ok((await geometry()).hourWidth <= fitted.hourWidth * 4 + 1, 'Pinch obeys the six-hour limit');
        assert.equal(await zoom.textContent(), '6h view');
        await client.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
        assert.equal(await page.evaluate(() => visualViewport.scale), 1, 'Pinch changes the ruler rather than browser zoom');
        assert.equal(await page.locator('#replay-handle').getAttribute('aria-label'), selectedTime);
        assert.equal(await rangeStartHandle.getAttribute('aria-label'), rangeTime);
        await client.detach();
        await fit();
      }
      await page.getByRole('button', { name: 'Play replay', exact: true }).click();
      await zoom.press('Space');
      assert.equal(await zoom.textContent(), '48h view', 'The view button supports keyboard activation');
      assert.equal(await page.locator('#play').getAttribute('aria-pressed'), 'true', 'Zoom preserves active playback');
      await fit();
      assert.equal(await page.locator('#play').getAttribute('aria-pressed'), 'true', 'Fit preserves active playback');
      await page.getByRole('button', { name: 'Pause replay', exact: true }).click();
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
      await page.waitForFunction(() => document.querySelector('#replay-handle')?.getAttribute('aria-label')?.includes('08:06'));
      assert.equal(await page.locator('#play').getAttribute('aria-pressed'), 'true', 'Resuming at the forecast end continues beyond the 24-hour window');
      await page.getByRole('button', { name: 'Pause replay', exact: true }).click();
      await page.getByRole('button', { name: 'Restart at forecast start', exact: true }).click();
      await page.locator('#replay-handle').press('PageDown');
      await page.locator('#replay-handle').press('PageDown');
      await page.locator('#replay-handle').press('PageDown');
      assert.match(await page.locator('#replay-handle').getAttribute('aria-label'), /Oct 4/, 'Replay seeks beyond the previous 48-hour boundary');
      await page.getByRole('button', { name: 'Play replay', exact: true }).click();
      await page.waitForFunction(() => document.querySelector('#replay-handle')?.getAttribute('aria-label')?.includes('08:06'));
      assert.equal(await page.locator('#play').getAttribute('aria-pressed'), 'true', 'Manual seeking beyond the forecast end bypasses the forecast pause');
      await page.getByRole('button', { name: 'Pause replay', exact: true }).click();
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
