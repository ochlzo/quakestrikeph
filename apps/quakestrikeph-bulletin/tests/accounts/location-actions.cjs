// Run against the account fixture server with PUBLIC_CLERK_PUBLISHABLE_KEY=FIXTURE_ONLY.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4333';

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [1440, 384]) {
      const page = await browser.newPage({ viewport: { width, height: 824 }, reducedMotion: 'reduce' });
      page.setDefaultTimeout(15000);
      let account = { userId: 'fixture-user', displayName: 'Maria', email: 'maria@example.invalid',
        phone: '+639171234567', onboardingCompleted: true, status: 'active', emailEnabled: true,
        smsEnabled: true, magnitude: 4.5, nearbyOnly: false,
        latitude: 13.21667, longitude: 123.51667, distanceKm: 50 };
      const writes = [];
      let fail = false, hold = false, release;
      await page.route('**/api/v1/account**', async route => {
        if (route.request().method() === 'PUT') {
          const body = route.request().postDataJSON();
          writes.push(body);
          if (fail) {
            fail = false;
            return route.fulfill({ status: 503, json: { error: { code: 'UNAVAILABLE', message: 'Removal failed. Try again.' } } });
          }
          if (hold) await new Promise(resolve => { release = resolve; });
          account = { ...account, ...body };
          return route.fulfill({ json: account });
        }
        return route.fulfill({ json: { account, pending: null, nextStep: 'complete' } });
      });
      await page.goto(`${root}/location?signed=1`, { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page.getByRole('button', { name: 'Edit', exact: true }).click();
      const options = page.getByRole('button', { name: 'Location options', exact: true });
      const heading = page.getByRole('heading', { name: 'Choose your alert location', exact: true });
      const box = await options.boundingBox(), title = await heading.boundingBox();
      assert.ok(Math.abs(box.y - title.y) < 2, 'Menu trigger must align with the top of the heading');
      assert.ok(box.x > title.x && box.x + box.width <= width);
      await options.focus();
      await options.press('Enter');
      await page.getByRole('menu', { name: 'Location options' }).waitFor();
      await page.screenshot({ path: require('node:path').join(require('node:os').tmpdir(), `location-actions-${width}.png`), fullPage: true });
      await page.keyboard.press('Escape');
      await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === 'Location options');
      assert.equal(await options.evaluate(node => document.activeElement === node), true);
      assert.equal(await heading.isVisible(), true, 'Escape must close the menu, not settings');
      await page.locator('#distance').fill('75');
      await options.click();
      const saved = page.waitForResponse(response => response.url().endsWith('/preferences') && response.request().method() === 'PUT');
      await page.getByRole('menuitem', { name: 'Save location', exact: true }).click();
      await page.getByRole('button', { name: 'Edit', exact: true }).waitFor();
      await saved;
      assert.equal(writes[0].distanceKm, 75);
      assert.equal(writes[0].nearbyOnly, true, 'Saving a location must enable nearby-only filtering');
      await page.getByRole('button', { name: 'Edit', exact: true }).click();
      await options.click();
      await page.getByRole('menuitem', { name: 'Remove location', exact: true }).click();
      const confirmation = page.getByRole('dialog', { name: 'Remove your alert location?' });
      await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click();
      assert.equal(writes.length, 1, 'Cancel must not save');
      await options.click();
      await page.getByRole('menuitem', { name: 'Remove location', exact: true }).click();
      fail = true;
      await confirmation.getByRole('button', { name: 'Remove location', exact: true }).click();
      await confirmation.getByRole('alert').waitFor();
      assert.match(await confirmation.getByRole('alert').innerText(), /Removal failed/);
      assert.equal(await page.locator('.location-controls .location-summary').getAttribute('data-selected'), 'true');
      hold = true;
      const requested = page.waitForRequest(request => request.url().endsWith('/preferences') && request.method() === 'PUT');
      await confirmation.getByRole('button', { name: 'Remove location', exact: true }).click();
      await requested;
      assert.equal(await page.getByText('No alert location yet', { exact: true }).count(), 0, 'Keep location until success');
      assert.equal(await confirmation.getByRole('button', { name: 'Removing…' }).isDisabled(), true);
      release();
      await page.getByText('No alert location yet', { exact: true }).waitFor();
      assert.deepEqual(writes.at(-1), { emailEnabled: true, smsEnabled: true, magnitude: 4.5,
        nearbyOnly: false, latitude: null, longitude: null, distanceKm: null });
      await page.getByRole('button', { name: 'Set location', exact: true }).click();
      await options.click();
      assert.equal(await page.getByRole('menuitem', { name: 'Remove location', exact: true }).count(), 0);
      assert.equal(await page.getByRole('menuitem', { name: 'Save location', exact: true }).count(), 1);
      await page.keyboard.press('Escape');
      await page.context().grantPermissions(['geolocation']);
      await page.context().setGeolocation({ latitude: 14.5995, longitude: 120.9842 });
      await page.getByRole('button', { name: 'Use my location', exact: true }).click();
      await page.locator('.location-controls .location-summary[data-selected="true"]').waitFor();
      hold = false;
      const created = page.waitForResponse(response => response.url().endsWith('/preferences') && response.request().method() === 'PUT');
      await page.getByRole('button', { name: 'Use this location', exact: true }).click();
      await created;
      assert.equal(writes.at(-1).nearbyOnly, true, 'A first location save must enable nearby-only filtering');
      assert.equal(writes.at(-1).latitude, 14.5995);
      const navRole = width > 760 ? 'button' : 'tab';
      await page.getByRole(navRole, { name: 'Alert preferences', exact: true }).click();
      const disabled = page.waitForResponse(response => response.url().endsWith('/preferences') && response.request().method() === 'PUT');
      await page.getByRole('switch', { name: 'Only earthquakes near my location', exact: true }).focus();
      await page.keyboard.press('Space');
      await disabled;
      assert.equal(writes.at(-1).nearbyOnly, false, 'The user can still disable the filter manually');
      await page.getByRole(navRole, { name: 'Alert location', exact: true }).click();
      await page.getByRole('button', { name: 'Edit', exact: true }).click();
      await page.locator('#distance').fill('80');
      await page.getByRole(navRole, { name: 'Alert preferences', exact: true }).click();
      const departure = page.getByRole('dialog', { name: 'Save changes?', exact: true });
      const confirmed = page.waitForResponse(response => response.url().endsWith('/preferences') && response.request().method() === 'PUT');
      await departure.getByRole('button', { name: 'Yes', exact: true }).click();
      await confirmed;
      await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      assert.equal(writes.at(-1).nearbyOnly, true, 'Saving through the departure confirmation must enable the filter');
      assert.equal(writes.at(-1).distanceKm, 80);
      assert.equal(await page.getByRole('switch', { name: 'Only earthquakes near my location', exact: true }).isChecked(), true);
      await page.close();
      console.log(`PASS location menu, save, removal cancel/failure/retry, and preserved preferences: ${width}`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
