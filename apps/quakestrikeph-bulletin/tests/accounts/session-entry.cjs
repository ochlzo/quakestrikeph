// Start: pnpm exec vite --config tests/accounts/vite.config.mjs
// Run with the bundled Playwright on NODE_PATH.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { mkdir } = require('node:fs/promises');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport });
      const tokenModes = [];
      page.on('console', message => {
        if (message.text().startsWith('fixture:token-mode:')) tokenModes.push(message.text());
      });
      await page.goto(`${root}/?header=1&signed=1`);
      await page.getByRole('link', { name: 'Alert settings', exact: true }).waitFor();
      await page.evaluate(() => window.dispatchEvent(new CustomEvent('fixture:auth', {
        detail: { userId: null, sessionId: null },
      })));
      await page.getByRole('link', { name: 'Receive alerts', exact: true }).waitFor();
      let release;
      const gate = new Promise(resolve => { release = resolve; });
      await page.route('**/api/v1/account', async route => {
        await gate;
        await route.fulfill({ json: {
          account: { userId: 'fixture-user', displayName: 'Maria Santos', email: 'maria@example.invalid',
            phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false,
            magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null },
          pending: null, nextStep: 'complete', deliveryAvailable: false,
        } });
      });
      await page.goto(`${root}/?signed=1`);
      await page.getByRole('status').filter({ hasText: 'Loading alert settings' }).waitFor();
      assert.equal(await page.locator('.preferences-loading [data-slot="skeleton"]').count(), 9);
      assert.equal(await page.getByRole('button', { name: 'Alert preferences', exact: true }).isEnabled(), false);
      assert.equal(await page.getByRole('button', { name: 'Alert location', exact: true }).isEnabled(), false);
      assert.equal(await page.getByRole('button', { name: 'Account', exact: true }).isEnabled(), false);
      await mkdir('.impeccable/review/alerts-skeleton', { recursive: true });
      await page.screenshot({ path: `.impeccable/review/alerts-skeleton/loading-${viewport.width}.png`, fullPage: true });
      assert.equal(await page.locator('.loading-tab, .loading-forgot, .google').count(), 0);
      assert.equal(await page.locator('.account-app').getAttribute('data-screen'), 'preferences');
      release();
      await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      await page.locator('.preferences-loading').waitFor({ state: 'detached' });
      await page.screenshot({ path: `.impeccable/review/alerts-skeleton/preferences-${viewport.width}.png`, fullPage: true });
      assert.deepEqual(tokenModes, ['fixture:token-mode:cached']);
      await page.route('**/api/v1/account/preferences', route => route.fulfill({ json: {
        ...route.request().postDataJSON(), userId: 'fixture-user', displayName: 'Maria Santos',
        email: 'maria@example.invalid', phone: null, onboardingCompleted: true, status: 'active',
      } }));
      await page.getByRole('button', { name: 'Save preferences', exact: true }).click();
      await page.getByText('Alert preferences saved.', { exact: true }).waitFor();
      assert.deepEqual(tokenModes, ['fixture:token-mode:cached', 'fixture:token-mode:fresh']);
      await page.goto(root);
      await page.getByRole('heading', { name: 'Sign in', exact: true }).waitFor();
      await page.close();
    }
    console.log('Session entry checks passed on desktop and mobile.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
