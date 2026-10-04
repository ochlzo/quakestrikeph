// Mocked requests exercise expiry and recovery without sending an SMS.
const assert = require('node:assert/strict');
const { mkdir } = require('node:fs/promises');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    await mkdir('.impeccable/review/accounts', { recursive: true });
    for (const width of [382, 1528]) {
      const page = await browser.newPage({ viewport: { width, height: 827 } });
      const writes = [];
      const account = { userId: '11111111-1111-4111-8111-111111111111', displayName: 'Maria', email: 'maria@example.com', phone: null, onboardingCompleted: false, status: 'active', emailEnabled: false, smsEnabled: false, magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null };
      const pending = (expired) => ({ id: 'attempt-1', phone: '+639171234567', expiresAt: new Date(Date.now() + (expired ? -1000 : 300000)).toISOString(), resendAt: new Date(Date.now() - 1000).toISOString() });
      await page.route('**/api/v1/account**', route => {
        const request = route.request();
        if (request.method() !== 'GET') writes.push(request.url().split('/account')[1]);
        return route.fulfill({ json: request.method() === 'GET'
          ? { account, pending: pending(true), nextStep: 'verify-phone', deliveryAvailable: false }
          : request.url().endsWith('/phone/attempts') ? pending(false) : account });
      });
      await page.goto('http://127.0.0.1:4332/?signed=1');
      const resend = page.getByRole('button', { name: 'Resend code', exact: true });
      await resend.waitFor();
      assert.equal(await page.getByRole('button', { name: 'Verify code', exact: true }).count(), 0);
      await page.getByLabel('Verification code', { exact: true }).fill('123456');
      await page.getByLabel('Verification code', { exact: true }).press('Enter');
      assert.deepEqual(writes, []);
      await page.screenshot({ path: `.impeccable/review/accounts/verify-expired-${width}.png`, fullPage: true });
      await resend.click();
      const verify = page.getByRole('button', { name: 'Verify code', exact: true });
      await verify.waitFor();
      assert.equal(await page.getByLabel('Verification code', { exact: true }).inputValue(), '');
      assert.deepEqual(writes, ['/phone/attempts']);
      assert.equal(await page.getByText('Smart and TNT numbers are currently unsupported.').count(), 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      assert.equal(await page.locator('.account').evaluate(el => getComputedStyle(el).borderRadius), width === 382 ? '0px' : '16px');
      await page.screenshot({ path: `.impeccable/review/accounts/verify-active-${width}.png`, fullPage: true });
      await page.getByLabel('Verification code', { exact: true }).fill('123456');
      await verify.click();
      await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      assert.deepEqual(writes, ['/phone/attempts', '/phone/verify']);
      await page.close();
    }
    console.log('Expired-code guard, resend recovery, verification, and desktop/mobile layouts passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
