// Run against the local Bulletin; search responses are held without live writes.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.BULLETIN_URL || 'http://localhost:4321';

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      let release;
      const responseReady = new Promise(resolve => { release = resolve; });
      await page.route('**/api/v1/earthquakes/search', async route => {
        if (route.request().postDataJSON().location) await responseReady;
        await route.fulfill({ json: { items: [], nextCursor: null, hasMore: false, fetchedAt: new Date().toISOString() } });
      });
      await page.goto(root, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => {
        const island = document.querySelector('astro-island[component-url*="Bulletin"]');
        return island && !island.hasAttribute('ssr');
      });
      if (width < 760) await page.getByRole('button', { name: 'Show earthquakes', exact: true }).click();
      const input = page.getByRole('textbox', { name: 'Search by Province', exact: true });
      const search = page.locator('.search-field:visible');
      await input.waitFor();
      const before = await input.boundingBox();
      await input.fill('Albay');
      const spinner = search.locator('[data-slot="spinner"]');
      await spinner.waitFor();
      assert.equal(await search.locator(':scope > svg').count(), 1, 'The spinner must replace the search icon.');
      assert.equal(await search.getAttribute('aria-busy'), 'true');
      const during = await input.boundingBox();
      assert.equal(during.x, before.x, 'Loading must not move the input.');
      assert.equal(during.width, before.width);
      release();
      await spinner.waitFor({ state: 'detached' });
      assert.equal(await search.locator(':scope > svg').count(), 1, 'The search icon must return after loading.');
      await page.close();
    }
    console.log('Search loading: leading spinner replacement and stable input placement passed on desktop and mobile.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
