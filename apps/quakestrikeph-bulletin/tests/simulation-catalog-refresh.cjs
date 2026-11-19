const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const url = new URL('/simulate-forecast', process.env.BULLETIN_URL || 'http://localhost:4321');
const previousCutoff = '2026-11-17T12:00:00.907929Z';
const recoveredCutoff = '2026-11-19T12:00:00Z';
const refreshWaitMs = 31_000;

function renderedCatalog(status, cutoff) {
  // The server-rendered page gets these values from the private Backend request.
  return {
    contentType: 'text/html',
    body: `<main id="simulator" data-catalog-status="${status}" data-catalog-cutoff="${cutoff}"
      data-guest-cookie-confirmed="true"></main>`,
  };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    let refreshResponse = renderedCatalog('stale', previousCutoff);
    await page.route((requestUrl) => requestUrl.origin !== url.origin, (route) => route.abort());
    await page.route((requestUrl) => requestUrl.origin === url.origin && requestUrl.pathname === url.pathname,
      (route) => route.request().isNavigationRequest() ? route.continue() : route.fulfill(refreshResponse));

    await page.clock.install();
    await page.goto(url.href, { waitUntil: 'domcontentloaded' });
    await page.locator('astro-island[component-url*="Simulation"][ssr]').waitFor({ state: 'detached' });
    const magnitude = page.locator('[name="magnitude"]');
    await magnitude.fill('5.24');

    const source = page.locator('.simulate-source:visible');
    const previousTime = source.locator(`time[datetime="${previousCutoff}"]`);
    const warning = source.getByText('Over 24 hours old', { exact: true });
    const enabledRun = page.locator('button.simulate-run:enabled');
    const disabledRun = page.locator('button.simulate-run:disabled');
    await page.clock.fastForward(refreshWaitMs);
    await enabledRun.waitFor();
    await previousTime.waitFor();
    assert.match(await previousTime.textContent(), /08:00:00\s+PM \(PHT\)$/);
    await source.getByText('The model needs seven days', { exact: false }).waitFor();
    for (const width of [1280, 384, 320]) {
      await page.setViewportSize({ width, height: 824 });
      await warning.waitFor();
      await page.evaluate(() => document.fonts.ready);
      const isBesideCutoff = await warning.evaluate((element) => {
        const time = element.previousElementSibling?.getBoundingClientRect();
        const note = element.getBoundingClientRect();
        const heading = element.closest('.simulate-source-heading').getBoundingClientRect();
        return time && time.right <= note.left && note.right <= heading.right && Math.abs(time.top - note.top) < 1;
      });
      assert.ok(isBesideCutoff, `The warning fits beside the cutoff at ${width}px`);
    }

    refreshResponse = { status: 502, body: 'Bad Gateway' };
    const failedRefresh = page.waitForResponse((response) => response.url() === url.href && response.status() === 502);
    await page.clock.fastForward(refreshWaitMs);
    await failedRefresh;
    await disabledRun.waitFor({ timeout: 5000 });
    await source.getByText('Unavailable', { exact: true }).waitFor();
    await page.locator('.simulate-feedback').getByText('The PHIVOLCS catalog could not be checked').waitFor();
    assert.equal(await previousTime.count(), 0);
    assert.equal(await warning.count(), 0);

    refreshResponse = renderedCatalog('current', recoveredCutoff);
    await page.clock.fastForward(refreshWaitMs);
    await enabledRun.waitFor({ timeout: 5000 });
    await source.locator(`time[datetime="${recoveredCutoff}"]`).waitFor();
    assert.equal(await warning.count(), 0);
    assert.equal(await page.locator('.simulate-feedback').count(), 0);
    assert.equal(await magnitude.inputValue(), '5.24');
    console.log('Catalog refresh: HTTP 502 clears the cutoff and disables Run until a successful refresh.');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
