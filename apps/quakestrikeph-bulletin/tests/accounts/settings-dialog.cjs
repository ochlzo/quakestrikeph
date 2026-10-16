// Real Astro navigation with fixture identity and account responses; no live account writes.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4333';

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    let account = { userId: 'fixture-user', displayName: 'Maria', email: 'maria@example.invalid',
      phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false,
      magnitude: 4.5, nearbyOnly: false, latitude: 13.2, longitude: 123.5, distanceKm: 50 };
    await page.route('**/api/v1/account**', route => {
      if (route.request().method() === 'PUT') {
        account = { ...account, ...route.request().postDataJSON() };
        return route.fulfill({ json: account });
      }
      return route.fulfill({ json: { account, pending: null, nextStep: 'complete' } });
    });
    const preferences = () => page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
    const close = () => page.locator('.account-settings-dialog > [data-slot="dialog"] > [data-slot="dialog-close"]').click();
    await page.goto(`${root}/alerts?signed=1`);
    await preferences();
    const bounds = await page.locator('.account-settings-dialog').boundingBox();
    assert.equal(bounds.width, 1120);
    assert.ok(bounds.height <= 810 && bounds.y >= 24);
    await page.reload();
    await preferences();
    assert.equal(await page.locator('#bulletin-view').getAttribute('aria-hidden'), 'true');
    await page.mouse.click(20, 20);
    assert.equal(new URL(page.url()).pathname, '/alerts');
    await page.locator('#magnitude').fill('6.2');
    await page.locator('#magnitude').press('Escape');
    assert.equal(await page.locator('#magnitude').inputValue(), '4.5');
    assert.equal(new URL(page.url()).pathname, '/alerts');
    await page.evaluate(() => { window.fixturePublicView = document.querySelector('#bulletin-view'); });
    await page.keyboard.press('Escape');
    await page.waitForURL(`${root}/`);
    assert.equal(await page.evaluate(() => window.fixturePublicView === document.querySelector('#bulletin-view')), true);

    await page.getByRole('link', { name: 'Alert settings', exact: true }).click();
    await preferences();
    await page.getByRole('button', { name: 'Alert location', exact: true }).click();
    assert.equal(new URL(page.url()).pathname, '/location');
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await page.locator('#distance').fill('100');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.querySelector('.account-settings-dialog').getBoundingClientRect().x === 0);
    assert.equal(await page.locator('#distance').inputValue(), '100');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: `${process.env.TEMP}/quakestrike-modal-check/location-mobile.png` });
    await page.setViewportSize({ width: 1440, height: 900 });
    await close();
    const confirmation = page.getByRole('dialog', { name: 'Save changes?', exact: true });
    await confirmation.waitFor();
    await page.keyboard.press('Escape');
    await confirmation.waitFor({ state: 'hidden' });
    assert.equal(await page.locator('#distance').inputValue(), '100');
    await page.goBack();
    await confirmation.getByRole('button', { name: 'No, discard it', exact: true }).click();
    await preferences();
    await page.goForward();
    await page.getByRole('heading', { name: 'Alert location', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Account', exact: true }).click();
    await page.getByRole('button', { name: 'Edit name', exact: true }).click();
    await page.locator('#name').fill('Maria Updated');
    await close();
    await confirmation.getByRole('button', { name: 'Yes', exact: true }).click();
    await page.waitForURL(`${root}/`);
    assert.equal(account.displayName, 'Maria Updated');
    assert.equal(await page.evaluate(() => window.fixturePublicView === document.querySelector('#bulletin-view')), true);
    const removedRoute = await page.request.get(`${root}/alerts/location`, { maxRedirects: 0 });
    assert.equal(removedRoute.status(), 404);
    assert.deepEqual(errors, []);
    console.log('Settings Dialog: size, dismissal, responsive draft, confirmation, history, and preserved background passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
