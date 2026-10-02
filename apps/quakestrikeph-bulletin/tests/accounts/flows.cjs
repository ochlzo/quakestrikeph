// Start: pnpm exec vite --config tests/accounts/vite.config.mjs
// Run with the bundled Playwright on NODE_PATH, like the existing Bulletin browser checks.
const assert = require('node:assert/strict');
const { mkdir, writeFile } = require('node:fs/promises');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const blank = { emailEnabled: false, smsEnabled: false, magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null };
const account = { ...blank, userId: '11111111-1111-4111-8111-111111111111', displayName: 'Maria Santos', email: 'maria@example.invalid',
  phone: null, onboardingCompleted: true, status: 'active' };
const output = '.impeccable/review/accounts';
(async () => {
  await mkdir(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const evidence = [], errors = [];
  async function setup(viewport, initialAccount = account, phoneFixture = false) {
    const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
    page.on('pageerror', e => errors.push(e.message));
    let current = initialAccount ? { ...initialAccount } : null;
    const writes = []; let failNext = false;
    await page.route('**/api/v1/account**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname.replace('/api/v1/account', ''), method = request.method();
      if (method === 'GET') return route.fulfill({ json: { account: current, pending: null, nextStep: !current ? 'profile' : current.onboardingCompleted ? 'complete' : 'channels', deliveryAvailable: false } });
      const body = request.postDataJSON(); writes.push({ path, method, body });
      if (failNext) { failNext = false; return route.fulfill({ status: 503, json: { error: { code: 'UNAVAILABLE', message: 'Please try saving again.' } } }); }
      if (phoneFixture && path === '/phone/attempts') {
        if (current.phone) current = { ...current, smsEnabled: false };
        return route.fulfill({ status: 201, json: { id: 'fixture-attempt', phone: '+639171234567',
          expiresAt: new Date(Date.now() + 300000).toISOString(), resendAt: new Date(Date.now() + 60000).toISOString() } });
      }
      if (phoneFixture && path === '/phone/verify') {
        if (body.code !== '111111') return route.fulfill({ status: 400, json: { error: { code: 'INVALID_CODE', field: 'code', message: 'That code did not work.' } } });
        current = { ...current, phone: '+639171234567', smsEnabled: false };
        return route.fulfill({ json: current });
      }
      if (path === '/profile') current = { ...(current || account), displayName: body.displayName, onboardingCompleted: current?.onboardingCompleted ?? false };
      else if (path === '/preferences') current = { ...current, ...body, onboardingCompleted: true };
      else return route.fulfill({ status: 503, json: { error: { code: 'SMS_UNAVAILABLE', message: 'SMS verification unavailable.' } } });
      return route.fulfill({ json: current });
    });
    return { page, writes, fail: () => { failNext = true; } };
  }
  async function capture(page, name) {
    await page.evaluate(() => document.fonts.ready);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${name} overflow`);
    await page.screenshot({ path: `${output}/${name}.png`, fullPage: true });
    evidence.push({ name, viewport: page.viewportSize(), url: page.url() });
  }
  try {
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      const size = viewport.width === 1440 ? 'desktop' : 'mobile';
      const f = await setup(viewport); const page = f.page;
      await page.goto(root); await page.getByRole('heading', { name: 'Sign in', exact: true }).waitFor();
      await capture(page, `signin-${size}`);
      await page.getByRole('textbox', { name: 'Email address' }).fill('test@example.invalid');
      await page.getByRole('textbox', { name: 'Password', exact: true }).fill('wrong-password');
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      await page.getByRole('alert').filter({ hasText: 'Sign-in did not work' }).waitFor();
      await page.getByRole('button', { name: 'Continue with Google' }).click();
      await page.getByRole('alert').filter({ hasText: 'Google sign-in was not completed' }).waitFor();
      await page.getByRole('button', { name: 'Show password', exact: true }).click();
      assert.equal(await page.locator('#password').getAttribute('type'), 'text');
      await page.getByRole('button', { name: 'Hide password', exact: true }).click();
      await page.getByRole('textbox', { name: 'Password', exact: true }).fill('fixture-password');
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      await page.getByRole('heading', { name: 'Verify your email' }).waitFor();
      await capture(page, `device-code-${size}`);
      await page.close();

      const p = (await setup(viewport)).page;
      await p.goto(`${root}/?signed=1`); await p.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      assert.equal(await p.getByRole('switch', { name: 'Email alerts', exact: true }).isChecked(), false);
      assert.equal(await p.getByRole('switch', { name: 'SMS alerts', exact: true }).isEnabled(), false);
      await capture(p, `preferences-${size}`);
      await p.getByRole('button', { name: 'Choose location', exact: true }).click();
      await p.getByRole('heading', { name: 'Choose your alert location' }).waitFor();
      await p.getByRole('combobox').pressSequentially('Davao');
      await p.getByRole('option').first().waitFor(); await p.getByRole('option').first().click();
      await p.getByRole('spinbutton', { name: 'Nearby distance (km)' }).fill('75');
      assert.equal(await p.getByRole('textbox', { name: /latitude|longitude|coordinate/i }).count(), 0);
      await p.locator('.location-map[data-map-ready="true"]').waitFor({ timeout: 45000 });
      await capture(p, `location-${size}`);
      await p.getByRole('button', { name: 'Use this location', exact: true }).click();
      await p.getByText(/Within 75 km/).waitFor();
      await p.getByRole('button', { name: 'Choose location', exact: true }).click();
      await p.getByRole('spinbutton', { name: 'Nearby distance (km)' }).fill('99');
      await p.getByRole('button', { name: 'Cancel', exact: true }).click();
      await p.getByText(/Within 75 km/).waitFor();
      await p.close();

      const a = (await setup(viewport, { ...account, phone: '+639171234567' })).page;
      await a.goto(`${root}/?signed=1&initial=account`); await a.getByRole('heading', { name: 'Account settings' }).waitFor();
      await capture(a, `account-${size}`);
      await a.getByRole('button', { name: 'Change', exact: true }).first().click();
      await a.getByRole('heading', { name: 'Email change is unavailable' }).waitFor();
      await a.getByRole('button', { name: 'Back to account settings' }).click();
      await a.getByRole('button', { name: 'Remove account' }).click();
      await a.getByRole('heading', { name: 'Account removal is unavailable' }).waitFor();
      await a.getByRole('button', { name: 'Back to account settings' }).click();
      await a.getByRole('button', { name: 'Change password' }).click();
      await a.getByRole('heading', { name: 'Verify your identity again' }).waitFor();
      await a.getByRole('textbox', { name: 'Current password', exact: true }).fill('fixture-password');
      await a.getByRole('button', { name: 'Verify identity', exact: true }).click();
      await a.getByRole('heading', { name: 'Change your password' }).waitFor();
      await capture(a, `password-${size}`); await a.close();
    }
    const phoneFlow = await setup({ width: 390, height: 844 }, { ...account, phone: '+639181234567', smsEnabled: true }, true);
    await phoneFlow.page.goto(`${root}/?signed=1&initial=account`);
    await phoneFlow.page.getByRole('button', { name: 'Change', exact: true }).nth(1).click();
    await phoneFlow.page.getByRole('textbox', { name: 'Current password', exact: true }).fill('fixture-password');
    await phoneFlow.page.getByRole('button', { name: 'Verify identity', exact: true }).click();
    await phoneFlow.page.getByRole('textbox', { name: 'New mobile number', exact: true }).fill('09171234567');
    await phoneFlow.page.getByRole('button', { name: 'Send verification code', exact: true }).click();
    await phoneFlow.page.getByRole('textbox', { name: 'Verification code' }).fill('999999');
    await phoneFlow.page.getByRole('button', { name: 'Verify mobile number', exact: true }).click();
    await phoneFlow.page.getByRole('alert').filter({ hasText: 'That code did not work.' }).waitFor();
    await phoneFlow.page.getByRole('textbox', { name: 'Verification code' }).fill('111111');
    await phoneFlow.page.getByRole('button', { name: 'Verify mobile number', exact: true }).click();
    await phoneFlow.page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
    assert.equal(await phoneFlow.page.getByRole('switch', { name: 'SMS alerts', exact: true }).isChecked(), false);
    await phoneFlow.page.getByRole('button', { name: 'Save preferences', exact: true }).click();
    await phoneFlow.page.getByText('Alert preferences saved.', { exact: true }).waitFor();
    assert.equal(phoneFlow.writes.at(-1).body.smsEnabled, false);
    await phoneFlow.page.close();
    const f = await setup({ width: 390, height: 844 });
    await f.page.goto(`${root}/?signed=1`);
    await f.page.getByRole('switch', { name: 'Email alerts', exact: true }).focus();
    await f.page.getByRole('switch', { name: 'Email alerts', exact: true }).press('Space');
    f.fail(); await f.page.getByRole('button', { name: 'Save preferences' }).click();
    await f.page.getByRole('alert').filter({ hasText: 'Please try saving again.' }).waitFor();
    assert.equal(await f.page.getByRole('switch', { name: 'Email alerts', exact: true }).isChecked(), true);
    await f.page.getByRole('button', { name: 'Save preferences' }).click();
    await f.page.getByText('Alert preferences saved.', { exact: true }).waitFor();
    assert.equal(f.writes.filter(x => x.path === '/preferences').length, 2);
    await f.page.close();
    const signup = await setup({ width: 390, height: 844 }, null);
    await signup.page.goto(`${root}/?initial=signup`);
    await signup.page.getByRole('textbox', { name: 'Name', exact: true }).fill('New Reader');
    await signup.page.getByRole('textbox', { name: 'Email address' }).fill('new@example.invalid');
    await signup.page.getByRole('textbox', { name: 'Password', exact: true }).fill('Fixture-password-long1');
    await signup.page.getByRole('button', { name: 'Create account' }).click();
    await signup.page.getByRole('textbox', { name: 'Verification code' }).fill('999999');
    await signup.page.getByRole('button', { name: 'Verify email' }).click();
    await signup.page.getByRole('alert').filter({ hasText: 'That code did not work' }).waitFor();
    await signup.page.getByRole('textbox', { name: 'Verification code' }).fill('111111');
    await signup.page.getByRole('button', { name: 'Verify email' }).click();
    await signup.page.getByRole('heading', { name: 'Complete your profile' }).waitFor();
    await signup.page.getByRole('button', { name: 'Continue', exact: true }).click();
    await signup.page.getByRole('heading', { name: 'How would you like to receive alerts?' }).waitFor();
    await signup.page.getByRole('radio', { name: /Email and SMS/ }).check();
    await signup.page.getByRole('button', { name: 'Continue', exact: true }).click();
    await signup.page.getByRole('heading', { name: 'Add your mobile number' }).waitFor();
    await signup.page.getByRole('button', { name: 'Continue without SMS' }).click();
    assert.equal(await signup.page.getByRole('switch', { name: 'Email alerts', exact: true }).isChecked(), false);
    await signup.page.getByRole('button', { name: 'Save preferences' }).click();
    await signup.page.waitForURL('**/?preferences=saved');
    assert.equal(signup.writes.at(-1).body.emailEnabled, false); assert.equal(signup.writes.at(-1).body.smsEnabled, false);
    await signup.page.close();
    assert.deepEqual(errors, []);
    await writeFile(`${output}/checks.json`, JSON.stringify({ status: 'passed', evidence, errors, providerMode: 'isolated fixtures; no live provider sends' }, null, 2));
    console.log('Account browser transitions and desktop/mobile captures passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
