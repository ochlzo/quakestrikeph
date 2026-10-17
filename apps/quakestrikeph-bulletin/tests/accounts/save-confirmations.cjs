// Run against the isolated accounts Vite fixture. No real identity or SMS calls.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const baseline = { userId: 'fixture-user', displayName: 'Maria', email: 'maria@example.invalid',
  phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, latitude: 13.21667, longitude: 123.51667, distanceKm: 50 };
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
      const response = deferred(), requested = deferred();
      let account = { ...baseline }, writes = 0;
      await page.route('**/api/v1/account**', async route => {
        if (route.request().method() === 'PUT') {
          const body = route.request().postDataJSON();
          if (++writes === 1) {
            requested.resolve();
            await response.promise;
            return route.fulfill({ status: 503, json: { message: 'Location save unavailable' } });
          }
          account = { ...account, ...body };
          return route.fulfill({ json: account });
        }
        return route.fulfill({ json: { account, nextStep: 'complete', pending: null } });
      });
      await page.goto(`${root}/location?signed=1`);
      await page.getByRole('button', { name: 'Edit', exact: true }).click();
      await page.locator('#distance').fill('100');
      await page.locator(viewport.width <= 760 ? '.settings-mobile-tabs' : '.settings-desktop-nav')
        .getByRole(viewport.width <= 760 ? 'tab' : 'button', { name: 'Account', exact: true }).click();
      await page.getByRole('dialog', { name: /^(Save changes\?|Changes could not be saved)$/ }).getByRole('button', { name: 'Yes', exact: true }).click();
      await requested.promise;
      assert.equal(new URL(page.url()).pathname, '/location');
      assert.equal(await page.getByRole('dialog', { name: /^(Save changes\?|Changes could not be saved)$/ }).getByRole('button', { name: 'Saving…', exact: true }).isDisabled(), true);
      assert.equal(await page.getByText('Alert preferences saved.', { exact: true }).count(), 0);
      response.resolve();
      const failure = page.getByRole('dialog', { name: 'Changes could not be saved' });
      await failure.waitFor();
      assert.equal(new URL(page.url()).pathname, '/location');
      assert.equal(await page.locator('#distance').inputValue(), '100');
      assert.equal(await page.locator('[data-slot="toast"]').count(), 0, 'Dialog failures must not also create a toast');
      await failure.getByRole('button', { name: 'Retry', exact: true }).click();
      await page.locator('.account-app[data-screen="account"]').waitFor();
      await page.getByText('Alert preferences saved.', { exact: true }).waitFor();
      assert.equal(account.distanceKm, 100);
      assert.equal(writes, 2);
      await page.close();

      const phonePage = await browser.newPage({ viewport, reducedMotion: 'reduce' });
      const optIn = deferred(), optInRequested = deferred(), emailSaved = deferred();
      account = { ...baseline, onboardingCompleted: false };
      const preferenceWrites = [];
      await phonePage.route('**/api/v1/account**', async route => {
        const request = route.request(), path = new URL(request.url()).pathname;
        if (request.method() === 'GET') return route.fulfill({ json: { account, nextStep: 'channels', pending: null } });
        if (path.endsWith('/phone/attempts')) return route.fulfill({ json: {
          id: 'attempt-1', phone: '+639171234567', expiresAt: new Date(Date.now() + 300000).toISOString(),
          resendAt: new Date(Date.now() + 60000).toISOString(),
        } });
        if (path.endsWith('/phone/verify')) {
          account = { ...account, phone: '+639171234567' };
          return route.fulfill({ json: account });
        }
        const body = request.postDataJSON();
        preferenceWrites.push(body);
        if (body.smsEnabled && preferenceWrites.length === 2) {
          optInRequested.resolve();
          await optIn.promise;
        }
        account = { ...account, ...body, onboardingCompleted: true };
        await route.fulfill({ json: account });
        if (preferenceWrites.length === 3) emailSaved.resolve();
      });
      await phonePage.goto(`${root}/onboarding?signed=1`);
      await phonePage.getByRole('button', { name: 'Continue', exact: true }).click();
      await phonePage.getByLabel('Mobile number', { exact: true }).fill('09171234567');
      await phonePage.getByRole('button', { name: 'Send verification code', exact: true }).click();
      await phonePage.getByLabel('Verification code', { exact: true }).fill('123456');
      await phonePage.getByRole('button', { name: 'Verify code', exact: true }).click();
      await optInRequested.promise;
      const email = phonePage.getByRole('switch', { name: 'Email alerts', exact: true });
      await email.focus();
      await email.press('Space');
      await phonePage.waitForTimeout(500); // Let the 400 ms debounce expire while the SMS write is held.
      assert.equal(preferenceWrites.length, 2, 'Channel edits must wait for the SMS opt-in write');
      optIn.resolve();
      await emailSaved.promise;
      assert.equal(preferenceWrites[2].smsEnabled, true);
      assert.equal(preferenceWrites[2].emailEnabled, true);
      assert.equal(account.smsEnabled, true);
      assert.equal(account.emailEnabled, true);
      await phonePage.close();

      const profilePage = await browser.newPage({ viewport, reducedMotion: 'reduce' });
      let profile = { ...baseline };
      await profilePage.route('**/api/v1/account**', async route => {
        if (route.request().method() === 'GET') return route.fulfill({ json: { account: profile, nextStep: 'complete', pending: null } });
        if (route.request().url().endsWith('/preferences')) return route.fulfill({ status: 503, json: {
          error: { code: 'UNAVAILABLE', message: 'Preference save unavailable' },
        } });
        profile = { ...profile, ...route.request().postDataJSON() };
        return route.fulfill({ json: profile });
      });
      const profileNavigate = label => profilePage.locator(viewport.width <= 760 ? '.settings-mobile-tabs' : '.settings-desktop-nav')
        .getByRole(viewport.width <= 760 ? 'tab' : 'button', { name: label, exact: true }).click();
      await profilePage.goto(`${root}/account?signed=1`);
      await profilePage.getByRole('button', { name: 'Edit name', exact: true }).click();
      await profilePage.locator('#name').fill('Ana');
      await profilePage.getByRole('button', { name: 'Save name', exact: true }).click();
      await profilePage.getByText('Profile saved.', { exact: true }).waitFor();
      await profileNavigate('Alert preferences');
      const profileEmail = profilePage.getByRole('switch', { name: 'Email alerts', exact: true });
      await profileEmail.focus();
      await profileEmail.press('Space');
      await profilePage.getByText('Preference save unavailable', { exact: true }).waitFor();
      await profilePage.locator('[data-slot="toast"]').filter({ hasText: 'Preference save unavailable' })
        .getByRole('button', { name: 'Close toast', exact: true }).click();
      await profileNavigate('Account');
      assert.equal(profile.displayName, 'Ana');
      assert.equal(await profilePage.locator('#name').inputValue(), 'Ana', 'Preference rollback must retain the saved profile name');
      await profilePage.getByRole('button', { name: 'Edit name', exact: true }).click();
      await profilePage.locator('#name').fill('Another draft');
      await profilePage.getByRole('button', { name: 'Discard name changes', exact: true }).click();
      assert.equal(await profilePage.locator('#name').inputValue(), 'Ana');
      await profilePage.close();

      const identityPage = await browser.newPage({ viewport, reducedMotion: 'reduce' });
      const oldResponse = deferred(), oldRequest = deferred(), oldFinished = deferred();
      await identityPage.route('**/api/v1/account**', async route => {
        if (route.request().method() === 'GET') return route.fulfill({ json: {
          account: { ...baseline, onboardingCompleted: false }, nextStep: 'channels', pending: null,
        } });
        oldRequest.resolve();
        await oldResponse.promise;
        await route.fulfill({ status: 503, json: { message: 'Former account save failed' } });
        oldFinished.resolve();
      });
      await identityPage.goto(`${root}/onboarding?signed=1`);
      await identityPage.getByRole('button', { name: 'Continue', exact: true }).click();
      await oldRequest.promise;
      await identityPage.evaluate(() => window.dispatchEvent(new CustomEvent('fixture:auth', {
        detail: { userId: null, sessionId: null },
      })));
      await identityPage.getByRole('heading', { name: 'Sign in', exact: true }).waitFor();
      assert.equal(await identityPage.locator('[data-slot="toast"]').count(), 0, 'Identity cancellation must not report the former save');
      oldResponse.resolve();
      await oldFinished.promise;
      assert.equal(await identityPage.locator('[data-slot="toast"]').count(), 0);
      await identityPage.close();
      console.log(`PASS ${viewport.width}: confirmed saves, SMS opt-in, profile rollback, and identity cancellation`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
