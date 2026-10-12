const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 382, height: 827 } });
    await page.route('**/api/v1/account**', route => route.fulfill(route.request().method() === 'GET'
      ? { json: { account: { userId: '11111111-1111-4111-8111-111111111111', displayName: 'Maria', email: 'maria@example.com', phone: null, onboardingCompleted: false, status: 'active', emailEnabled: false, smsEnabled: false, magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null }, pending: null, nextStep: 'phone', deliveryAvailable: false } }
      : { status: 429, json: { error: { code: 'SEND_LIMIT', message: 'Wait 60 seconds between code requests.' } } }));
    await page.goto(`${root}/?signed=1`);
    await page.getByLabel('Mobile number', { exact: true }).fill('09171234567');
    await page.getByRole('button', { name: 'Send verification code' }).click();
    await page.locator('[data-slot="toast-title"]').filter({ hasText: 'Wait 60 seconds' }).waitFor();
    assert.equal(await page.locator('.screen-focus').getByText('Wait 60 seconds between code requests.', { exact: true }).count(), 0);
    assert.deepEqual(await page.locator('[data-slot="toast-viewport"]').evaluate(el => {
      const s = getComputedStyle(el); return [s.position, s.top, s.right];
    }), ['fixed', '16px', '16px']);
    await page.getByLabel('Mobile number', { exact: true }).fill('');
    await page.getByRole('button', { name: 'Send verification code' }).click();
    await page.locator('#phone-error').getByText('Mobile number is required.', { exact: true }).waitFor();
    console.log('Send-limit toast, mobile top-right placement, and inline field validation passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
