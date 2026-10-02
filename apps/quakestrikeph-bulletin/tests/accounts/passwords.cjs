// Browser validation against the isolated Clerk fixture; no provider requests.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const account = {
  userId: '11111111-1111-4111-8111-111111111111', displayName: 'Fixture Reader',
  email: 'fixture@example.invalid', phone: null, emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null,
  onboardingCompleted: true, status: 'active',
};

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  try {
    async function setup(query = '') {
      const page = await browser.newPage();
      const writes = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => {
        if (message.text().startsWith('fixture:password-write:')) writes.push(message.text());
      });
      await page.route('**/api/v1/account', route => route.fulfill({ json: {
        account, pending: null, nextStep: 'complete', deliveryAvailable: false,
      } }));
      await page.goto(root + '/?' + query);
      return { page, writes };
    }

    async function validate(page, writes, button) {
      await page.locator('#confirm-password').fill('Abcdefg1');
      for (const invalid of ['Abcdef1', 'abcdefg1', 'ABCDEFG1', 'Abcdefgh']) {
        await page.locator('#new-password').fill(invalid);
        assert.equal(await page.locator('#new-password').evaluate(el => el.checkValidity()), false);
        await page.getByRole('button', { name: button, exact: true }).click();
        assert.equal(writes.length, 0, 'Invalid passwords must not reach Clerk');
      }
      await page.getByRole('button', { name: 'Show new password', exact: true }).click();
      assert.equal(await page.locator('#new-password').getAttribute('type'), 'text');
      assert.equal(await page.locator('#new-password').evaluate(el => el.checkValidity()), false);
      await page.getByRole('button', { name: 'Hide new password', exact: true }).click();
      await page.locator('#new-password').fill('Abcdefg1');
      assert.equal(await page.locator('#new-password').evaluate(el => el.checkValidity()), true);
      await page.locator('#confirm-password').fill('Abcdefg2');
      await page.getByRole('button', { name: button, exact: true }).click();
      await page.getByText('The passwords do not match.', { exact: true }).waitFor();
      assert.equal(writes.length, 0);
      await page.locator('#confirm-password').fill('Abcdefg1');
    }

    const recovery = await setup();
    await recovery.page.getByRole('heading', { name: 'Sign in', exact: true }).waitFor();
    await recovery.page.locator('#password').fill('old');
    assert.equal(await recovery.page.locator('#password').evaluate(el => el.checkValidity()), true);
    await recovery.page.getByRole('button', { name: 'Forgot password?', exact: true }).click();
    await recovery.page.locator('#email').fill('fixture@example.invalid');
    await recovery.page.getByRole('button', { name: 'Send recovery code', exact: true }).click();
    await recovery.page.locator('#code').fill('111111');
    await recovery.page.getByRole('button', { name: 'Verify code', exact: true }).click();
    await recovery.page.getByRole('heading', { name: 'Choose a new password' }).waitFor();
    await validate(recovery.page, recovery.writes, 'Save new password');
    await recovery.page.getByRole('button', { name: 'Save new password', exact: true }).click();
    await recovery.page.getByRole('heading', { name: 'Alert preferences' }).waitFor();
    assert.deepEqual(recovery.writes, ['fixture:password-write:recovery']);
    await recovery.page.close();

    for (const passwordless of [false, true]) {
      const flow = await setup('signed=1&initial=account' + (passwordless ? '&passwordless=1' : ''));
      await flow.page.getByRole('button', { name: passwordless ? 'Add password' : 'Change password', exact: true }).click();
      if (passwordless) {
        await flow.page.locator('#code').fill('111111');
      } else {
        // New-password composition must not apply to the current factor.
        await flow.page.locator('#current-password').fill('fixture-password');
        assert.equal(await flow.page.locator('#current-password').getAttribute('pattern'), null);
      }
      await flow.page.getByRole('button', { name: 'Verify identity', exact: true }).click();
      await flow.page.getByRole('heading', { name: passwordless ? 'Add password sign-in' : 'Change your password' }).waitFor();
      if (!passwordless) await flow.page.locator('#current-password').fill('fixture-password');
      await validate(flow.page, flow.writes, 'Save password');
      await flow.page.getByRole('button', { name: 'Save password', exact: true }).click();
      await flow.page.getByText('Password saved.', { exact: true }).waitFor();
      assert.deepEqual(flow.writes, ['fixture:password-write:update']);
      await flow.page.close();
    }

    const task = await setup('signed=1&task=reset-password&password-error=1');
    await task.page.getByRole('heading', { name: 'Choose a new password' }).waitFor();
    await validate(task.page, task.writes, 'Save new password');
    await task.page.getByRole('button', { name: 'Save new password', exact: true }).click();
    await task.page.getByText('The password could not be saved. Please try again.', { exact: true }).waitFor();
    assert.equal(task.writes.length, 0);
    await task.page.getByRole('button', { name: 'Save new password', exact: true }).click();
    await task.page.waitForURL('**/alerts?entry=1');
    assert.deepEqual(task.writes, ['fixture:password-write:update']);
    await task.page.close();
    assert.deepEqual(errors, []);
    console.log('Recovery, password addition/change, required reset, mismatch, retry and existing-password checks passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
