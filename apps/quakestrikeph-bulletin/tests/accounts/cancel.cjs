// Isolated profile cancellation; no Clerk provider requests.
const assert = require('node:assert/strict');
const { mkdir } = require('node:fs/promises');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    await mkdir('.impeccable/review/accounts', { recursive: true });
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      const writes = [], errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/api/v1/account**', route => {
        if (route.request().method() !== 'GET') writes.push(route.request().method());
        return route.fulfill({ json: { account: null, pending: null, nextStep: 'profile', deliveryAvailable: false } });
      });
      await page.goto(`${root}/?signed=1&signout-error=1`);
      await page.getByRole('heading', { name: 'Complete your profile' }).waitFor();
      assert.equal(await page.locator('.profile-email').textContent(), 'maria@example.com');
      const cancel = page.getByRole('button', { name: 'Cancel and sign out', exact: true });
      // Cancel works even when the required Name field is empty.
      await cancel.click();
      await page.getByRole('alert').filter({ hasText: 'Sign-out could not be completed. Please try again.' }).waitFor();
      assert.equal(await cancel.isEnabled(), true);
      assert.deepEqual(writes, []);
      await page.goto(`${root}/?signed=1`);
      await page.getByRole('heading', { name: 'Complete your profile' }).waitFor();
      await page.getByRole('textbox', { name: 'Name', exact: true }).fill('Unsaved reader');
      await page.evaluate(() => document.fonts.ready);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.screenshot({ path: `.impeccable/review/accounts/profile-cancel-${width}.png`, fullPage: true });
      // Observe the home redirect without rendering the account fixture again.
      await page.route(`${root}/`, route => route.fulfill({ contentType: 'text/html', body: '<h1>Public Bulletin</h1>' }));
      await cancel.focus();
      await cancel.press('Enter');
      await page.waitForURL(`${root}/`);
      await page.getByRole('heading', { name: 'Public Bulletin' }).waitFor();
      assert.deepEqual(writes, []);
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('Profile cancellation, failure recovery, keyboard operation, and desktop/mobile checks passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
