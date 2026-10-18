// Run against the account fixture server with PUBLIC_CLERK_PUBLISHABLE_KEY=FIXTURE_ONLY.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4333';

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [1440, 384]) {
      for (const hasLocation of [false, true]) {
        const page = await browser.newPage({ viewport: { width, height: 900 }, reducedMotion: 'reduce' });
        await page.route('**/api/v1/account**', route => route.fulfill({ json: {
          account: { userId: 'fixture-user', displayName: 'Maria', email: 'maria@example.invalid',
            phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false,
            smsEnabled: false, magnitude: 4.5, nearbyOnly: false,
            latitude: hasLocation ? 14.5995 : null, longitude: hasLocation ? 120.9842 : null,
            distanceKm: hasLocation ? 50 : null },
          pending: null, nextStep: 'complete',
        } }));
        await page.goto(`${root}/alerts?signed=1`, { waitUntil: 'domcontentloaded' });
        await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
        await page.locator('.screen-focus[aria-busy="false"]').waitFor();
        const section = page.locator('.nearby-section');
        assert.equal(await section.getByRole('switch').count(), hasLocation ? 1 : 0);
        assert.equal(await section.locator('.location-summary').count(), hasLocation ? 1 : 0);
        assert.equal(await section.getByRole('button', { name: 'Set location', exact: true }).count(), hasLocation ? 0 : 1);
        if (hasLocation) {
          assert.equal(await section.getByRole('switch').isChecked(), false);
          assert.match(await section.locator('.location-summary').innerText(), /Within 50 km/);
          await section.getByRole('link').click();
          await page.waitForURL('**/location');
          await page.getByRole('button', { name: 'Edit', exact: true }).click();
          const summary = page.locator('.location-controls .location-summary');
          await summary.waitFor();
          assert.equal(await summary.getAttribute('data-selected'), 'true');
          assert.equal(await summary.locator('svg').count(), 1);
          assert.doesNotMatch(await summary.innerText(), /Choose your alert location/);
          const search = page.locator('.location-search input');
          assert.equal(await search.inputValue(), '');
          await search.fill('Manila');
          await search.fill('');
          assert.equal(await summary.isVisible(), true, 'Clearing search must keep the selected pin summary');
        } else {
          const setup = section.getByRole('button', { name: 'Set location', exact: true });
          assert.equal(await setup.getAttribute('class'), await page.getByRole('button', { name: 'Add number', exact: true }).getAttribute('class'));
          await setup.focus();
          assert.equal(await setup.evaluate(node => document.activeElement === node), true);
          assert.equal(await setup.evaluate(node => node.getBoundingClientRect().right <= innerWidth), true);
          await setup.press('Enter');
          await page.waitForURL('**/location');
        }
        await page.close();
        console.log(`PASS nearby location ${hasLocation ? 'saved' : 'missing'}: ${width}`);
      }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
