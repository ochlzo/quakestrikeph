// Start the account fixture server before running this browser regression check.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const baseline = { userId: 'fixture-user', displayName: 'Maria', email: 'maria@example.invalid',
  phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, latitude: 13.21667, longitude: 123.51667, distanceKm: 50 };

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const viewport of [{ width: 1559, height: 884 }, { width: 384, height: 824 }]) {
      const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
      let account = { ...baseline, latitude: null, longitude: null, distanceKm: null };
      let writes = [], fail = false;
      await page.route('**/api/v1/account**', async route => {
        if (route.request().method() === 'PUT') {
          if (fail) return route.fulfill({ status: 500, json: { message: 'Save unavailable' } });
          const body = route.request().postDataJSON();
          writes.push(body);
          account = { ...account, ...body };
          return route.fulfill({ json: account });
        }
        return route.fulfill({ json: { account, nextStep: 'complete' } });
      });
      const edit = () => page.getByRole('button', { name: 'Edit', exact: true }).click();
      const navigate = label => page.locator(viewport.width <= 760 ? '.settings-mobile-tabs' : '.settings-desktop-nav')
        .getByRole(viewport.width <= 760 ? 'tab' : 'button', { name: label, exact: true }).click();
      await page.goto(`${root}/alerts/location?signed=1`);
      await page.getByText('No alert location yet', { exact: true }).waitFor();
      assert.equal(await page.locator('.location-map').count(), 0);
      assert.equal(await page.locator('[data-slot="empty-icon"] .lucide-earth').count(), 1);
      await page.screenshot({ path: `C:/Users/cholo/.codex/visualizations/2026/10/06/01a10ed2-23cb-7282-b68b-c65bda2bc29f/location-empty-${viewport.width}.png` });
      await page.getByRole('button', { name: 'Set location', exact: true }).click();
      assert.equal(await page.locator('.location-map').count(), 1);
      await page.getByRole('button', { name: 'Use this location', exact: true }).click();
      await page.locator('[data-slot="toast"]').getByText('Choose a location using search or the map.', { exact: true }).waitFor();
      assert.equal(await page.locator('#location-pin-error').count(), 0);
      assert.equal(await page.getByRole('combobox').getAttribute('aria-invalid'), 'false');
      assert.equal(await page.locator('.location-summary svg').evaluate(e => getComputedStyle(e).color), 'rgb(228, 32, 27)');
      await page.getByRole('button', { name: 'Cancel', exact: true }).click();
      assert.equal(await page.locator('.location-map').count(), 0);

      account = { ...baseline };
      await page.goto(`${root}/alerts/location?signed=1`);
      await page.locator('.location-view-distance').waitFor();
      assert.equal(await page.locator('.location-view-distance').innerText(), 'Within 50 km');
      await edit();
      await page.locator('#distance').fill('0');
      await navigate('Account');
      await page.getByRole('dialog').getByRole('button', { name: 'Yes', exact: true }).click();
      await page.getByRole('dialog').waitFor({ state: 'hidden' });
      await page.locator('#distance-error').waitFor();
      assert.equal(await page.locator('#distance').getAttribute('aria-invalid'), 'true');
      await page.locator('#distance').fill('100');
      await page.getByRole('button', { name: 'Cancel', exact: true }).click();
      assert.equal(await page.locator('.location-view-distance').innerText(), 'Within 50 km');
      await edit();
      await page.locator('#distance').fill('100');
      await navigate('Account');
      const dialog = page.getByRole('dialog', { name: 'Save changes?' });
      await dialog.waitFor();
      const box = await page.locator('[data-slot="dialog-content"]').boundingBox();
      assert.ok(Math.abs(box.x + box.width / 2 - viewport.width / 2) < 2);
      assert.ok(Math.abs(box.y + box.height / 2 - viewport.height / 2) < 2);
      const footer = await page.locator('.unsaved-actions').evaluate(e => {
        const buttons = [...e.querySelectorAll('button')].map(button => button.getBoundingClientRect());
        return { direction: getComputedStyle(e).flexDirection, border: getComputedStyle(e).borderTopWidth,
          aligned: Math.abs(buttons[0].top - buttons[1].top) < 1 };
      });
      assert.equal(footer.direction, 'row');
      assert.equal(footer.border, '0px');
      assert.ok(footer.aligned);
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#distance').inputValue(), '100');
      await navigate('Account');
      fail = true;
      await dialog.getByRole('button', { name: 'Yes', exact: true }).click();
      await page.getByRole('dialog', { name: 'Changes could not be saved' }).waitFor();
      assert.equal(new URL(page.url()).pathname, '/alerts/location');
      fail = false;
      await page.getByRole('dialog').getByRole('button', { name: 'Retry', exact: true }).click();
      await page.locator('.account-app[data-screen="account"]').waitFor();
      assert.equal(writes.length, 1);
      assert.equal(writes[0].distanceKm, 100);
      await page.locator('[data-slot="toast"]').getByText('Alert preferences saved.', { exact: true }).waitFor();
      assert.equal(await page.locator('[data-slot="toast-icon"] .lucide-circle-check').evaluate(e => getComputedStyle(e).color), 'oklch(0.527 0.154 150.069)');
      await navigate('Alert location');
      await edit();
      await page.locator('#distance').fill('200');
      await navigate('Account');
      await dialog.getByRole('button', { name: 'No, discard it', exact: true }).click();
      await navigate('Alert location');
      assert.equal(await page.locator('.location-view-distance').innerText(), 'Within 100 km');
      assert.equal(writes.length, 1);
      await edit();
      await page.locator('#distance').fill('200');
      await page.goBack();
      await dialog.waitFor();
      await page.waitForURL('**/alerts/location');
      await dialog.getByRole('button', { name: 'No, discard it', exact: true }).click();
      await page.locator('.account-app[data-screen="account"]').waitFor();
      await page.close();
      console.log(`PASS ${viewport.width}x${viewport.height}: empty state, edit/cancel, save failure, save and discard navigation`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
