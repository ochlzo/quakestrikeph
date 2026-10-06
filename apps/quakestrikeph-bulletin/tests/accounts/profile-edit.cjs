// Isolated account UI checks; no live identity or account writes.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const baseline = { userId: 'fixture-user', displayName: 'Maria Santos', email: 'maria@example.invalid', phone: null,
  onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false, magnitude: 4.5,
  nearbyOnly: false, latitude: null, longitude: null, distanceKm: null };
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      page.on('pageerror', error => errors.push(error.message));
      let account = { ...baseline }, mode = 'success', writes = 0, release;
      await page.route('**/api/v1/account**', async route => {
        if (route.request().method() === 'GET') return route.fulfill({ json: { account, nextStep: 'complete', pending: null } });
        writes++;
        if (mode === 'pending') await new Promise(resolve => { release = resolve; });
        if (mode === 'network') return route.abort('failed');
        if (mode === 'failure') return route.fulfill({ status: 503, json: { error: { code: 'UNAVAILABLE', message: 'Profile service unavailable.' } } });
        if (!route.request().postDataJSON().displayName.trim()) return route.fulfill({ status: 400,
          json: { error: { code: 'INVALID_NAME', field: 'displayName', message: 'Enter a name of 1–100 characters.' } } });
        account = { ...account, ...route.request().postDataJSON() };
        return route.fulfill({ json: account });
      });
      await page.goto(`${root}/account?signed=1`);
      const name = page.locator('#name');
      await page.getByRole('button', { name: 'Edit name' }).waitFor();
      assert.equal(await name.getAttribute('readonly'), '');
      assert.equal(await page.getByRole('button', { name: 'Save profile' }).count(), 0);
      await page.getByRole('button', { name: 'Edit name' }).click();
      assert.equal(await name.getAttribute('readonly'), null);
      assert.equal(await name.evaluate(input => input === document.activeElement), true);
      const save = page.getByRole('button', { name: 'Save name', exact: true });
      const discard = page.getByRole('button', { name: 'Discard name changes', exact: true });
      assert.equal(await save.evaluate(button => getComputedStyle(button).color), 'rgb(21, 128, 61)');
      for (const button of [save, discard]) assert.equal(await button.evaluate(button => getComputedStyle(button).backgroundColor), 'rgba(0, 0, 0, 0)');
      await name.fill('Draft name'); await discard.click();
      assert.equal(await name.inputValue(), baseline.displayName); assert.equal(writes, 0);
      await page.getByRole('button', { name: 'Edit name' }).click();
      await name.fill(''); await save.click();
      await page.locator('#name-error').getByText('Name is required.', { exact: true }).waitFor();
      assert.equal(writes, 0);
      await name.fill('   '); await save.click();
      await page.locator('#name-error').getByText('Enter a name of 1–100 characters.', { exact: true }).waitFor();
      assert.equal(await page.locator('[data-slot="toast"]').count(), 0);
      await discard.click(); assert.equal(await page.locator('#name-error').count(), 0);
      await page.getByRole('button', { name: 'Edit name' }).click();
      await name.fill('Maria Reyes'); mode = 'failure';
      for (let attempt = 0; attempt < 2; attempt++) {
        await save.click();
        await page.locator('[data-slot="toast"]').getByText('Profile service unavailable.', { exact: true }).waitFor();
        await page.waitForFunction(() => document.querySelector('.screen-focus').getAttribute('aria-busy') === 'false');
      }
      assert.equal(await page.locator('[data-slot="toast"]').count(), 1, 'Repeated action failures reuse one toast');
      assert.equal(await page.locator('.screen-focus [data-slot="field-error"]').count(), 0);
      assert.equal(await name.inputValue(), 'Maria Reyes');
      mode = 'network'; await save.click();
      await page.locator('[data-slot="toast"]').getByText('This request could not be completed. Please try again.', { exact: true }).waitFor();
      mode = 'pending'; await save.click();
      await page.waitForFunction(() => document.querySelector('[aria-label="Save name"]').disabled);
      assert.equal(await discard.isDisabled(), true);
      assert.equal(await name.isDisabled(), true);
      mode = 'success'; release();
      await page.locator('[data-slot="toast"]').getByText('Profile saved.', { exact: true }).waitFor();
      await page.getByRole('button', { name: 'Edit name' }).waitFor();
      assert.equal(await name.getAttribute('readonly'), '');
      assert.equal(account.displayName, 'Maria Reyes');
      await page.goto(`${root}/account?signed=1`);
      await page.getByRole('button', { name: 'Edit name' }).click();
      await name.fill('Another draft'); mode = 'failure';
      await page.getByRole('button', { name: 'Change', exact: true }).first().click();
      await page.getByRole('dialog').getByRole('button', { name: 'Yes', exact: true }).click();
      await page.getByRole('dialog', { name: 'Changes could not be saved' }).waitFor();
      assert.equal(await page.locator('[data-slot="toast"]').count(), 0, 'Dialog failures must not also create a toast');
      await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click();
      await name.press('Escape');
      assert.equal(await name.inputValue(), 'Maria Reyes');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.close();
    }
    assert.deepEqual(errors, []);
    console.log('Profile editing, field validation, toast reuse, pending saves, discard, and dialog errors passed on desktop and mobile.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
