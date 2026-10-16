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
    for (const viewport of [{ width: 1559, height: 884 }, { width: 390, height: 844 }]) {
      for (const mode of ['denied', 'unavailable', 'success']) {
        const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
        await page.route('**/api/v1/account**', route => route.fulfill({ json: { account, nextStep: 'complete' } }));
        await page.addInitScript(mode => Object.defineProperty(navigator, 'geolocation', {
          configurable: true,
          value: mode === 'unavailable' ? undefined : {
            getCurrentPosition(success, failure) {
              if (mode === 'success') success({ coords: { latitude: 14.6, longitude: 120.98 } });
              else failure({ code: 1 });
            },
          },
        }), mode);
        await page.goto(`${root}/location?signed=1`);
        await page.getByRole('button', { name: 'Edit', exact: true }).click();
        const locate = page.getByRole('button', { name: 'Use my location', exact: true });
        await locate.waitFor();
        const summary = page.locator('.location-controls .location-summary');
        const initial = await summary.innerText();
        await locate.click();
        const message = mode === 'unavailable'
          ? 'Location is unavailable on this device. Search or choose a map pin.'
          : 'Your location could not be used. Search for a place or choose a map pin.';
        if (mode === 'success') {
          await page.waitForFunction(initial => document.querySelector('.location-controls .location-summary').textContent.trim() !== initial, initial);
          assert.equal(await page.locator('[data-slot="toast"]').count(), 0);
        } else {
          const toast = page.locator('[data-slot="toast"]');
          await toast.getByText(message, { exact: true }).waitFor();
          assert.equal(await page.locator('.location-controls').getByText(message, { exact: true }).count(), 0);
          assert.equal(await summary.innerText(), initial, 'Location failure must preserve the selected pin');
          await page.waitForFunction(() => {
            const toast = document.querySelector('[data-slot="toast"]');
            return toast && !toast.hasAttribute('data-starting-style');
          });
          const box = await toast.boundingBox();
          assert.ok(Math.abs(viewport.width - box.x - box.width - 16) < 2, 'Toast must align right');
          assert.ok(viewport.width <= 760 ? box.y >= 15 && box.y <= 18
            : Math.abs(viewport.height - box.y - box.height - 16) < 2, 'Toast must use the requested vertical position');
          await locate.click();
          assert.equal(await toast.count(), 1, 'Retry must reuse the same toast');
          await toast.getByRole('button', { name: 'Close toast' }).click();
          await toast.waitFor({ state: 'detached' });
        }
        assert.ok(await locate.isEnabled(), 'Location button must recover after the request');
        await page.close();
        console.log(`PASS ${viewport.width}x${viewport.height}: ${mode}`);
      }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
