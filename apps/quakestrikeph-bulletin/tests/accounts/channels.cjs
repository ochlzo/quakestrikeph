// Provisional choices never write alert preferences or contact a provider.
const assert = require('node:assert/strict');
const { mkdir } = require('node:fs/promises');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    await mkdir('.impeccable/review/accounts', { recursive: true });
    for (const viewport of [{ width: 1528, height: 867 }, { width: 390, height: 827 }, { width: 390, height: 600 }]) {
      const { width, height } = viewport;
      const page = await browser.newPage({ viewport });
      const writes = [], errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/api/v1/account**', route => {
        if (route.request().method() !== 'GET') writes.push(route.request().method());
        return route.fulfill({ json: { account: {
          userId: '11111111-1111-4111-8111-111111111111', displayName: 'Maria',
          email: 'maria@example.com', phone: null, onboardingCompleted: false, status: 'active',
          emailEnabled: false, smsEnabled: false, magnitude: 4.5, nearbyOnly: false,
          latitude: null, longitude: null, distanceKm: null,
        }, pending: null, nextStep: 'channels', deliveryAvailable: false } });
      });
      const sms = page.getByRole('checkbox', { name: /^SMS/ });
      const email = page.getByRole('checkbox', { name: /^Email/ });
      const neither = page.getByRole('checkbox', { name: /^Neither for now/ });
      const next = page.getByRole('button', { name: 'Continue', exact: true });
      await page.goto(`${root}/?signed=1`);
      await sms.waitFor();
      assert.deepEqual(await page.locator('.choice strong').allTextContents(), ['SMS', 'Email', 'Neither for now']);
      assert.equal(await sms.isChecked(), true);
      assert.equal(await email.isChecked(), false);
      assert.equal(await neither.isChecked(), false);
      await page.evaluate(() => document.fonts.ready);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      assert.equal(await page.evaluate(() => getComputedStyle(document.body).overflow), 'hidden');
      await page.evaluate(() => window.scrollTo(0, 500));
      assert.equal(await page.evaluate(() => window.scrollY), 0);
      assert.equal(await page.locator('.account').evaluate(el => el.scrollHeight > el.clientHeight), height === 600);
      assert.equal(await page.locator('.account h2').evaluate(el => getComputedStyle(el).marginTop), '0px');
      if (width === 390) {
        assert.equal(await page.locator('.account').evaluate(el => getComputedStyle(el).borderRadius), '0px');
        assert.equal(await page.locator('.account-app').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(255, 255, 255)');
      } else {
        assert.deepEqual(await page.locator('.account').evaluate(el => {
          const style = getComputedStyle(el);
          return [style.paddingTop, style.paddingBottom];
        }), ['24px', '24px']);
      }
      await page.screenshot({ path: `.impeccable/review/accounts/channels-${width}-${height}.png`, fullPage: true });
      await next.click();
      await page.getByRole('heading', { name: 'Add your mobile number' }).waitFor();
      await page.goto(`${root}/?signed=1`);
      await email.check();
      assert.equal(await sms.isChecked(), true);
      await neither.check();
      assert.equal(await sms.isChecked(), false);
      assert.equal(await email.isChecked(), false);
      await email.focus();
      await email.press('Space');
      assert.equal(await neither.isChecked(), false);
      await next.click();
      await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      assert.equal(await page.getByRole('switch', { name: 'Email alerts', exact: true }).isChecked(), false);
      await page.goto(`${root}/?signed=1`);
      await email.check();
      await next.click();
      await page.getByRole('heading', { name: 'Add your mobile number' }).waitFor();
      await page.goto(`${root}/?signed=1`);
      await sms.uncheck();
      assert.equal(await neither.isChecked(), true);
      await next.click();
      await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      assert.deepEqual(writes, []);
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('SMS default, independent choices, Neither exclusion, keyboard operation, routing, and desktop/mobile checks passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
