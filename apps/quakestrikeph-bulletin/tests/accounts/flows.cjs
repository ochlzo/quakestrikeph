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
  async function setup(viewport, initialAccount = account) {
    const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
    page.on('pageerror', e => errors.push(e.message));
    let current = { ...initialAccount };
    await page.route('**/api/v1/account**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname.replace('/api/v1/account', ''), method = request.method();
      if (method === 'GET') return route.fulfill({ json: { account: current, pending: null, nextStep: 'complete', deliveryAvailable: false } });
      assert.equal(path, '/preferences');
      assert.equal(method, 'PUT');
      current = { ...current, ...request.postDataJSON() };
      return route.fulfill({ json: current });
    });
    return { page };
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
      await page.getByText('Sign-in unsuccessful', { exact: true }).waitFor();
      await page.getByRole('button', { name: 'Continue with Google' }).click();
      await page.getByText('Google sign-in was not completed. Try again or use your password.', { exact: true }).waitFor();
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
      assert.equal(await p.getByRole('button', { name: 'Add number', exact: true }).isEnabled(), true);
      await capture(p, `preferences-${size}`);
      await p.locator('.alert-location-link').click();
      await p.getByRole('button', { name: 'Set location', exact: true }).click();
      await p.getByRole('heading', { name: 'Choose your alert location' }).waitFor();
      await p.getByRole('combobox').pressSequentially('Davao');
      await p.getByRole('option').first().waitFor(); await p.getByRole('option').first().click();
      await p.getByRole('textbox', { name: 'Nearby distance (km)' }).fill('75');
      assert.equal(await p.getByRole('textbox', { name: /latitude|longitude|coordinate/i }).count(), 0);
      await p.locator('.location-map[data-map-ready="true"]').waitFor({ timeout: 45000 });
      await capture(p, `location-${size}`);
      await p.getByRole('button', { name: 'Use this location', exact: true }).click();
      await p.getByText(/Within 75 km/).waitFor();
      await p.getByRole('button', { name: 'Edit', exact: true }).click();
      await p.getByRole('textbox', { name: 'Nearby distance (km)' }).fill('99');
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
    assert.deepEqual(errors, []);
    await writeFile(`${output}/checks.json`, JSON.stringify({ status: 'passed', evidence, errors, providerMode: 'isolated fixtures; no live provider sends' }, null, 2));
    console.log('Account browser transitions and desktop/mobile captures passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
