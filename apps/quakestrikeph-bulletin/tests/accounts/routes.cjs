// Isolated route and history checks. Clerk and account requests use fixtures.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { mkdir } = require('node:fs/promises');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const baseAccount = { userId: 'fixture-user', displayName: 'Maria Santos', email: 'maria@example.invalid',
  phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null };
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
      page.on('pageerror', error => errors.push(error.message));
      let account = { ...baseAccount }, pending = null, nextStep = 'complete', gets = 0;
      await page.route('**/api/v1/account**', route => {
        const request = route.request(), path = new URL(request.url()).pathname;
        if (request.method() === 'GET') { gets++; return route.fulfill({ json: { account, pending, nextStep, deliveryAvailable: false } }); }
        if (path.endsWith('/preferences')) { account = { ...account, ...request.postDataJSON(), onboardingCompleted: true }; nextStep = 'complete'; }
        return route.fulfill({ json: account });
      });
      for (const path of ['/alerts', '/location', '/account', '/account/password', '/account/phone', '/onboarding']) {
        await page.goto(`${root}${path}?signed=0`);
        await page.getByRole('heading', { name: 'Sign in', exact: true }).waitFor();
        assert.equal(new URL(page.url()).pathname, '/sign-in');
        assert.equal(await page.locator('.settings-rail').count(), 0);
      }
      for (const [path, heading] of [
        ['/alerts', 'Alert preferences'], ['/location', 'Alert location'],
        ['/account', 'Account settings'], ['/account/phone', 'Add your mobile number'],
        ['/account/password', 'Verify your identity'],
      ]) {
        await page.goto(`${root}${path}?signed=1`);
        await page.getByRole('heading', { name: heading, exact: true }).waitFor();
        assert.equal(new URL(page.url()).pathname, path);
        await page.reload();
        await page.getByRole('heading', { name: heading, exact: true }).waitFor();
      }
      await page.goto(`${root}/alerts?signed=1`);
      await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      if (viewport.width <= 760) assert.equal(await page.getByRole('button', { name: 'Toggle sidebar' }).getAttribute('aria-expanded'), 'false');
      else assert.equal(await page.locator('.account-app').getByRole('button', { name: 'Toggle sidebar' }).count(), 0);
      if (viewport.width > 760) {
        assert.equal(await page.locator('.account-settings-dialog').isVisible(), true);
        assert.equal(await page.getByRole('button', { name: 'Alert location', exact: true }).isVisible(), true);
      } else {
        assert.equal(await page.locator('.account-settings-dialog').evaluate(el => el.getBoundingClientRect().x), 0);
        assert.equal(await page.getByRole('tab', { name: 'Alert location', exact: true }).isVisible(), true);
      }
      await page.locator('#magnitude').fill('6.2');
      const magnitudeSaved = page.waitForResponse(response => response.request().method() === 'PUT');
      await page.getByRole('button', { name: 'Save magnitude', exact: true }).click();
      await (await magnitudeSaved).finished();
      const before = gets;
      await page.getByRole(viewport.width <= 760 ? 'tab' : 'button', { name: 'Alert location', exact: true }).click();
      await page.getByRole('heading', { name: 'Alert location', exact: true }).waitFor();
      assert.equal(new URL(page.url()).pathname, '/location');
      await page.goBack();
      await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      assert.equal(await page.locator('#magnitude').inputValue(), '6.2');
      await page.goForward();
      await page.getByRole('heading', { name: 'Alert location', exact: true }).waitFor();
      await page.getByRole(viewport.width <= 760 ? 'tab' : 'button', { name: 'Alert preferences', exact: true }).click();
      assert.equal(await page.locator('#magnitude').inputValue(), '6.2');
      assert.equal(gets, before, 'Local settings navigation must not reload the account');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await mkdir('.impeccable/review/account-routes', { recursive: true });
      await page.screenshot({ path: `.impeccable/review/account-routes/preferences-${viewport.width}.png`, fullPage: true });
      await page.getByRole(viewport.width <= 760 ? 'tab' : 'button', { name: 'Account', exact: true }).click();
      assert.equal(new URL(page.url()).pathname, '/account');
      await page.screenshot({ path: `.impeccable/review/account-routes/account-${viewport.width}.png`, fullPage: true });
      await page.goBack();
      await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      await page.getByRole(viewport.width <= 760 ? 'tab' : 'button', { name: 'Account', exact: true }).click();
      await page.getByRole('button', { name: 'Edit name', exact: true }).click();
      await page.locator('#name').fill('Unsaved name');
      await page.goBack();
      await page.getByRole('dialog', { name: 'Save changes?' }).waitFor();
      await page.keyboard.press('Escape');
      await page.waitForURL('**/account');
      assert.equal(await page.locator('#name').inputValue(), 'Unsaved name');
      await page.getByRole('button', { name: 'Discard name changes', exact: true }).click();

      // Completion routes return to preferences without a homepage redirect.
      for (const path of ['/sign-in', '/sign-up', '/forgot-password', '/onboarding', '/alerts?entry=1']) {
        await page.goto(`${root}${path}${path.includes('?') ? '&' : '?'}signed=1`);
        await page.locator('.account-loading').waitFor({ state: 'detached' });
        await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
        assert.equal(new URL(page.url()).pathname, '/alerts');
      }
      // A pending phone attempt resumes its verification screen on a direct visit.
      pending = { id: 'fixture-attempt', phone: '+639171234567', expiresAt: new Date(Date.now()+300000).toISOString(), resendAt: new Date(Date.now()+60000).toISOString() };
      await page.goto(`${root}/account/phone?signed=1`);
      await page.getByRole('heading', { name: 'Verify your mobile number', exact: true }).waitFor();
      assert.equal(new URL(page.url()).pathname, '/account/phone');
      pending = null;
      account = { ...baseAccount, onboardingCompleted: false }; nextStep = 'channels';
      await page.goto(`${root}/account?signed=1`);
      await page.getByRole('heading', { name: 'How would you like to receive alerts?', exact: true }).waitFor();
      assert.equal(new URL(page.url()).pathname, '/onboarding');
      await page.getByRole('checkbox', { name: /^Email/ }).check();
      await page.getByRole('checkbox', { name: /^SMS/ }).uncheck();
      await page.getByRole('button', { name: 'Continue', exact: true }).click();
      await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      await page.waitForURL('**/alerts');
      assert.equal(account.onboardingCompleted, true);
      await page.close();
    }
    assert.deepEqual(errors, []);
    console.log('Direct routes, refresh, authentication guards, history, drafts, phone recovery and onboarding passed on desktop and mobile.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
