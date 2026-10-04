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
      for (const signed of [0, 1]) {
        const pendingPage = await browser.newPage({ viewport });
        await pendingPage.route('**/clerk-fixture.tsx*', async route => {
          const response = await route.fetch();
          const source = await response.text();
          assert(source.includes('isLoaded: true'), 'Fixture must expose the authentication loading state');
          await route.fulfill({ response, body: source.replace('isLoaded: true', 'isLoaded: false') });
        });
        await pendingPage.goto(`${root}/?signed=${signed}`);
        await pendingPage.locator('.account-loading').waitFor();
        assert.equal(await pendingPage.locator('.preferences-loading').count(), 0,
          'Unresolved authentication must not show preferences');
        assert.equal(await pendingPage.locator('.account-app').getAttribute('data-screen'), 'signin');
        assert.equal(await pendingPage.locator('.settings-rail').count(), 0);
        assert.equal(await pendingPage.locator('.loading-tab').count(), 2);
        await pendingPage.close();
      }
      const page = await browser.newPage({ viewport });
      const tokenModes = [];
      page.on('console', message => {
        if (message.text().startsWith('fixture:token-mode:')) tokenModes.push(message.text());
      });
      await page.goto(`${root}/?header=1&signed=1`);
      await page.getByRole('link', { name: 'Alert settings', exact: true }).waitFor();
      assert.equal(await page.getByRole('link', { name: 'Alert settings', exact: true }).getAttribute('href'), '/alerts');
      await page.evaluate(() => window.dispatchEvent(new CustomEvent('fixture:auth', {
        detail: { userId: null, sessionId: null },
      })));
      await page.getByRole('link', { name: 'Receive alerts', exact: true }).waitFor();
      assert.equal(await page.getByRole('link', { name: 'Receive alerts', exact: true }).getAttribute('href'), '/sign-in');
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
      await page.goto(`${root}/?signed=0`);
      await page.getByRole('heading', { name: 'Sign in', exact: true }).waitFor();
      await page.close();
      for (const entry of ['initial=signin', 'initial=signup', 'entry=1']) {
        const entryPage = await browser.newPage({ viewport });
        await entryPage.route('**/api/v1/account', route => route.fulfill({ json: {
          account: { userId: 'fixture-user', displayName: 'Maria Santos', email: 'maria@example.invalid',
            phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false,
            magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null },
          pending: null, nextStep: 'complete', deliveryAvailable: false,
        } }));
        await entryPage.goto(`${root}/?signed=1&${entry}`);
        await entryPage.locator('.preferences-loading').waitFor({ state: 'detached' });
        await entryPage.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
        assert.equal(new URL(entryPage.url()).pathname, '/alerts',
          `Completed sign-in from ${entry} must return to preferences`);
        await entryPage.close();
      }
    }
    console.log('Session entry checks passed on desktop and mobile.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
