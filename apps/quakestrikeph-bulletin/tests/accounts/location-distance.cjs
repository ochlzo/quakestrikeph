// Start the account fixture server before running this browser regression check.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const account = { userId: 'fixture-user', displayName: 'Maria', email: 'maria@example.invalid',
  phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, latitude: 13.21667, longitude: 123.51667, distanceKm: 50 };

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const viewport of [{ width: 1559, height: 884 }, { width: 384, height: 824 }]) {
      const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
      await page.route('**/api/v1/account**', route => route.fulfill({ json: { account, nextStep: 'complete' } }));
      await page.goto(`${root}/alerts/location?signed=1`);
      await page.getByRole('button', { name: 'Edit', exact: true }).click();
      const input = page.getByRole('textbox', { name: 'Nearby distance (km)' });
      await input.waitFor();
      assert.equal(await input.getAttribute('type'), 'text');
      assert.equal(await input.getAttribute('inputmode'), 'numeric');
      await input.fill('50');
      await input.press('ArrowUp');
      assert.equal(await input.inputValue(), '50', 'Native number stepping must be absent');
      for (const value of ['letters', '50km', '5.5', '-1', '1e2']) {
        await input.fill(value);
        assert.equal(await input.inputValue(), '50', 'Distance must reject non-digit input');
      }
      for (const value of ['', '0', '1001']) {
        await input.fill(value);
        await page.getByRole('button', { name: 'Use this location', exact: true }).click();
        assert.ok(new URL(page.url()).pathname.endsWith('/alerts/location'));
        assert.ok(await page.getByText('Enter a whole-kilometre distance from 1 to 1,000 km.', { exact: true }).isVisible());
      }
      await input.fill('1000');
      await page.getByRole('button', { name: 'Use this location', exact: true }).click();
      await page.getByRole('button', { name: 'Edit', exact: true }).waitFor();
      assert.ok(new URL(page.url()).pathname.endsWith('/alerts/location'));
      assert.equal(await page.locator('.location-view-distance').innerText(), 'Within 1000 km');
      await page.close();
      console.log(`PASS ${viewport.width}x${viewport.height}: numeric input, no stepping, range validation, draft update`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
