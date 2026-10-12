// Runs an isolated Astro server and public API fixture; no development data is changed.
const assert = require('node:assert/strict');
const { createServer } = require('node:http');
const { spawn } = require('node:child_process');
const { resolve } = require('node:path');
const { chromium } = require('playwright');
const root = 'http://127.0.0.1:4333';
const items = Array.from({ length: 30 }, (_, index) => ({
  eventId: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
  eventTime: '2026-10-05T04:00:00Z', magnitude: 2.5, latitude: 13, longitude: 123,
  depthKm: 10, locationDescription: `Server result ${index}`, forecast: null,
}));
const response = { items, fetchedAt: '2026-10-05T05:00:00Z', nextCursor: null, hasMore: false };
(async () => {
  let fail = false;
  const api = createServer((_request, reply) => {
    reply.writeHead(fail ? 503 : 200, { 'Content-Type': 'application/json' });
    reply.end(JSON.stringify(fail ? {} : response));
  });
  await new Promise(resolve => api.listen(4334, '127.0.0.1', resolve));
  const { NODE_PATH: _bundledPackages, ...serverEnv } = process.env;
  const server = spawn(process.execPath, [resolve('node_modules/astro/bin/astro.mjs'), 'dev', '--host', '127.0.0.1', '--port', '4333'], {
    env: { ...serverEnv, API_TARGET: 'http://127.0.0.1:4334' }, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let output = '';
  server.stdout.on('data', data => { output = (output + data).slice(-4000); });
  server.stderr.on('data', data => { output = (output + data).slice(-4000); });
  let browser;
  try {
    let ready = false;
    for (let attempt = 0; attempt < 80; attempt++) {
      if (server.exitCode !== null) break;
      try { ready = (await fetch(root)).ok; } catch {}
      if (ready) break;
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    assert(ready, `Isolated Astro server must start: ${output}`);
    browser = await chromium.launch({ channel: 'msedge', headless: true });
    const staticPage = await browser.newPage({ javaScriptEnabled: false });
    await staticPage.goto(root);
    assert.equal(await staticPage.locator('.event-row-v2').count(), 30, 'Initial HTML must contain 30 rows without JavaScript');
    assert.equal(await staticPage.locator('.event-list-skeleton').count(), 0);
    await staticPage.close();
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.addInitScript(({ items }) => {
        sessionStorage.setItem('quakestrike-earthquakes-v1', JSON.stringify({
          query: JSON.stringify({ limit: 30 }), items: items.map(row => ({ ...row, locationDescription: 'Older cached result' })),
          fetchedAt: '2026-10-04T05:00:00Z',
        }));
        window.blankList = false;
        let hadRows = false;
        new MutationObserver(() => {
          if (document.querySelector('.event-row-v2')) hadRows = true;
          else if (hadRows) window.blankList = true;
        }).observe(document, { subtree: true, childList: true });
      }, { items });
      let release, browserSearches = 0;
      await page.route('**/api/v1/earthquakes/search', async route => {
        if (browserSearches++ === 0) await new Promise(resolve => { release = resolve; });
        await route.fulfill({ json: { ...response, items: [{ ...items[0], locationDescription: 'Updated server result' }, ...items.slice(1)] } });
      });
      await page.goto(root, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => document.querySelectorAll('astro-island[ssr]').length === 0);
      if (viewport.width < 760) await page.getByRole('button', { name: 'Show earthquakes', exact: true }).click();
      await page.getByText('Server result 0', { exact: true }).waitFor();
      assert.equal(await page.getByText('Server result 0', { exact: true }).count(), 1);
      assert.equal(await page.getByText('Older cached result', { exact: true }).count(), 0,
        'Fresh server results must not be replaced by older browser data');
      assert.equal(await page.locator('.event-list-skeleton').count(), 0);
      if (viewport.width >= 760) assert.equal(await page.evaluate(() => window.blankList), false,
        'Desktop hydration must preserve the initial list');
      while (!release) await new Promise(resolve => setTimeout(resolve, 25));
      release();
      await page.waitForFunction(() => document.querySelector('.event-row-v2')?.textContent.includes('Updated server result'), {}, { timeout: 10000 }).catch(async error => {
        console.error({ viewport, errors, rows: await page.locator('.event-row-v2').allTextContents() });
        throw error;
      });
      const restoredRefresh = page.waitForResponse(response => response.url().includes('/earthquakes/search'));
      await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
      await restoredRefresh;
      assert.equal(browserSearches, 2, 'Restoring a persisted page must refresh the list');
      assert.equal(await page.locator('.event-row-v2').count(), 30);
      assert.equal(await page.locator('.event-list-skeleton').count(), 0);
      assert.deepEqual(errors, []);
      await page.close();
    }
    // Existing cache checks cover fallback when the server cannot obtain initial rows.
    fail = true;
    await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, ['tests/earthquake-cache.cjs'], {
        env: { ...process.env, BULLETIN_URL: root }, windowsHide: true, stdio: 'inherit',
      });
      child.on('error', reject);
      child.on('exit', code => code === 0 ? resolve() : reject(new Error(`Cache checks exited ${code}`)));
    });
    console.log('Initial HTML, hydration without a blank list, server freshness, background updates and persisted-page refresh passed.');
  } finally {
    if (browser) await browser.close();
    server.kill();
    await new Promise(resolve => api.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
