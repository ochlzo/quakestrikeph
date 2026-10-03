// Isolated authentication changes; no Clerk or SMS provider requests.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const original = {
  userId: '11111111-1111-4111-8111-111111111111', displayName: 'Original reader',
  email: 'original@example.invalid', phone: '+639171234567', emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, latitude: 13.14, longitude: 123.74, distanceKm: 50,
  onboardingCompleted: true, status: 'active',
};
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    let current = original, releaseWrite, writeStarted;
    const writeReady = new Promise(resolve => { writeStarted = resolve; });
    const writeGate = new Promise(resolve => { releaseWrite = resolve; });
    await page.route('**/api/v1/account**', async route => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: { account: current, pending: null, nextStep: 'complete', deliveryAvailable: false } });
      }
      writeStarted();
      await writeGate;
      return route.fulfill({ json: original });
    });
    await page.goto(`${root}/?signed=1`);
    await page.getByText(original.email, { exact: false }).waitFor();
    await page.getByRole('button', { name: 'Save preferences', exact: true }).click();
    await writeReady;
    const changeAuth = identity => page.evaluate(detail => {
      window.dispatchEvent(new CustomEvent('fixture:auth', { detail }));
    }, identity);
    await changeAuth({ userId: null, sessionId: null });
    await page.getByRole('heading', { name: 'Sign in', exact: true }).waitFor();
    assert.equal(await page.getByText(original.email, { exact: false }).count(), 0);
    assert.equal(await page.getByText(original.phone, { exact: false }).count(), 0);
    current = { ...original, displayName: 'Second reader', email: 'second@example.invalid', phone: null,
      latitude: null, longitude: null, distanceKm: null };
    await changeAuth({ userId: 'second-user', sessionId: 'second-session' });
    await page.getByText(current.email, { exact: false }).waitFor();
    const oldResponse = page.waitForResponse(response => response.request().method() === 'PUT');
    releaseWrite();
    await oldResponse;
    // Allow the old response body and its promise handlers to finish.
    await page.waitForTimeout(300);
    assert.equal(await page.getByText(original.email, { exact: false }).count(), 0);
    assert.equal(await page.getByText('Alert preferences saved.', { exact: true }).count(), 0);
    await page.getByText(current.email, { exact: false }).waitFor();
    current = { ...current, email: 'third@example.invalid' };
    await changeAuth({ userId: 'third-user', sessionId: 'third-session' });
    await page.getByText(current.email, { exact: false }).waitFor();
    assert.equal(await page.getByText('second@example.invalid', { exact: false }).count(), 0);
    current = { ...current, magnitude: 6.2 };
    await changeAuth({ userId: 'third-user', sessionId: 'renewed-session' });
    await page.getByRole('spinbutton', { name: 'Minimum earthquake magnitude' }).waitFor();
    assert.equal(await page.getByRole('spinbutton', { name: 'Minimum earthquake magnitude' }).inputValue(), '6.2');
    assert.deepEqual(errors, []);
    console.log('Sign-out, identity switch, session switch and delayed write isolation passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
