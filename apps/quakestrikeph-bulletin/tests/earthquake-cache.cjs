// Run against the local Bulletin with bundled Playwright on NODE_PATH.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { mkdir } = require('node:fs/promises');
const root = process.env.BULLETIN_URL || 'http://localhost:4321';
const key = 'quakestrike-earthquakes-v1';
const fixtures = Array.from({ length: 60 }, (_, index) => ({
  eventId: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
  eventTime: '2026-10-05T04:00:00Z', magnitude: 2.5, latitude: 13, longitude: 123,
  depthKm: 10, locationDescription: `Sample location ${index}`, forecast: null,
}));
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport });
      let items = fixtures.slice(0, 30), mode = 'live', release, requests = 0;
      await page.addInitScript(() => {
        window.sawListSkeleton = false;
        new MutationObserver(() => {
          if (document.querySelector('.event-list-skeleton')) window.sawListSkeleton = true;
        }).observe(document, { childList: true, subtree: true });
      });
      await page.route('**/api/v1/earthquakes/search', async route => {
        requests++;
        const body = route.request().postDataJSON();
        if (mode === 'hold') await new Promise(resolve => { release = resolve; });
        if (mode === 'fail') return route.fulfill({ status: 503, json: {} });
        const result = body.cursor ? fixtures.slice(30) : items;
        return route.fulfill({ json: { items: result, nextCursor: body.cursor ? null : 'page-2',
          hasMore: !body.cursor, fetchedAt: '2026-10-05T05:00:00Z' } });
      });
      const rows = page.locator('.event-row-v2:not(.event-row-skeleton)');
      const showList = async () => {
        await page.locator('astro-island[ssr]').waitFor({ state: 'detached' });
        if (viewport.width < 760) await page.getByRole('button', { name: 'Show earthquakes', exact: true }).click();
      };
      const cachedCount = () => page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).items.length, key);
      await page.goto(root, { waitUntil: 'domcontentloaded' });
      await showList();
      await rows.first().waitFor();
      assert.equal(await rows.count(), 30);
      assert.equal(await cachedCount(), 30);
      await page.getByRole('link', { name: 'Load more earthquakes', exact: true }).evaluate(link => link.click());
      await page.waitForFunction(() => document.querySelectorAll('.event-row-v2:not(.event-row-skeleton)').length === 60);
      assert.equal(await cachedCount(), 30, 'Pagination must not enlarge the cache');

      mode = 'hold';
      release = undefined;
      await page.reload({ waitUntil: 'domcontentloaded' });
      await showList();
      await rows.first().waitFor();
      assert.equal(await rows.count(), 30);
      assert.equal(await page.evaluate(() => window.sawListSkeleton), false, 'Cached reload must not show a skeleton');
      assert.equal(await page.getByRole('link', { name: 'Load more earthquakes', exact: true }).count(), 0,
        'Pagination must wait for a fresh cursor');
      assert.equal(await page.getByText(/Saved results ·/).count(), 0);
      items = [{ ...fixtures[0], magnitude: 5.1, locationDescription: 'Revised location' },
        { ...fixtures[59], locationDescription: 'New earthquake' }, ...fixtures.slice(2, 30)];
      while (!release) await new Promise(resolve => setTimeout(resolve, 25));
      mode = 'live';
      release();
      await page.getByText('Revised location', { exact: true }).waitFor();
      assert.equal(await page.getByText('Sample location 1', { exact: true }).count(), 0);
      assert.equal(await page.getByText('New earthquake', { exact: true }).count(), 1);

      mode = 'fail';
      await page.goto(`${root}/alerts`, { waitUntil: 'domcontentloaded' });
      const before = requests;
      const failedRefresh = page.waitForResponse(response => response.url().includes('/earthquakes/search') && response.status() === 503);
      await page.goto(root, { waitUntil: 'domcontentloaded' });
      await showList();
      await failedRefresh;
      await page.getByText('Revised location', { exact: true }).waitFor();
      assert.equal(await page.getByText(/Saved results ·/).count(), 0);
      assert.equal(await rows.count(), 30, 'Failed refresh must retain saved rows');
      assert(requests > before, 'Returning from alerts must refresh earthquakes');
      assert.equal(await page.evaluate(() => window.sawListSkeleton), false);
      await mkdir('.impeccable/review/earthquake-cache', { recursive: true });
      await page.screenshot({ path: `.impeccable/review/earthquake-cache/saved-${viewport.width}.png`, fullPage: true });

      for (const invalid of ['{broken', JSON.stringify({ query: 'different filters', items, fetchedAt: '2026-10-05T05:00:00Z' })]) {
        await page.evaluate(({ key, invalid }) => sessionStorage.setItem(key, invalid), { key, invalid });
        mode = 'hold'; release = undefined;
        await page.reload({ waitUntil: 'domcontentloaded' });
        await showList();
        await page.locator('.event-list-skeleton').waitFor();
        assert.equal(await rows.count(), 0, 'Unusable cache must not supply rows');
        while (!release) await new Promise(resolve => setTimeout(resolve, 25));
        mode = 'live'; release();
        await rows.first().waitFor();
      }
      await page.addInitScript(() => {
        Storage.prototype.getItem = () => { throw new Error('Storage unavailable'); };
        Storage.prototype.setItem = () => { throw new Error('Storage unavailable'); };
      });
      await page.reload({ waitUntil: 'domcontentloaded' });
      await showList();
      await rows.first().waitFor();
      assert.equal(await rows.count(), 30, 'Unavailable storage must not block live rows');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.close();
    }
    console.log('30-row cache, pagination, reload, reconciliation, alerts return, failure and storage fallback passed on desktop and mobile.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
