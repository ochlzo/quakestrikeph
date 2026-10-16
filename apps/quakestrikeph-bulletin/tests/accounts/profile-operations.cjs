// Run against the isolated accounts Vite fixture. No live account or provider calls.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const baseline = {
  userId: 'fixture-user', displayName: 'Maria Santos', email: 'maria@example.invalid',
  phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null,
};
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
async function waitForRequest(signal) {
  let timer;
  try {
    await Promise.race([signal.promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('The profile request did not start.')), 10000);
    })]);
  } finally { clearTimeout(timer); }
}

async function fixture(browser, viewport, errors, completed = true) {
  const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  const state = { account: completed ? { ...baseline } : null, writes: [], reads: [], trace: [], tokens: [] };
  page.on('console', message => {
    if (message.text().startsWith('fixture:token-mode:')) state.tokens.push(message.text());
  });
  await page.route('**/api/v1/account**', async route => {
    const request = route.request();
    if (request.method() === 'GET') {
      state.trace.push('GET');
      const reply = state.reads.shift();
      if (reply?.requested) reply.requested.resolve();
      if (reply?.gate) await reply.gate.promise;
      if (reply?.failure) return route.fulfill({ status: 503, json: {
        error: { code: 'UNAVAILABLE', message: reply.failure },
      } });
      return route.fulfill({ json: { account: state.account, pending: null,
        nextStep: !state.account ? 'profile' : state.account.onboardingCompleted ? 'complete' : 'channels' } });
    }
    assert.equal(new URL(request.url()).pathname, '/api/v1/account/profile');
    assert.equal(request.method(), 'PUT');
    const body = request.postDataJSON();
    state.trace.push(`PUT:${body.displayName}`);
    const previous = state.account;
    const saved = { ...(previous ?? baseline), onboardingCompleted: completed, ...body };
    const reply = state.writes.shift();
    if (reply?.requested) reply.requested.resolve();
    if (reply?.gate) await reply.gate.promise;
    if (reply?.failure) return route.fulfill({ status: 503, json: {
      error: { code: 'UNAVAILABLE', message: reply.failure },
    } });
    if (reply?.field) return route.fulfill({ status: 400, json: {
      error: { code: 'INVALID_NAME', field: 'displayName', message: reply.field },
    } });
    if (state.account === previous) state.account = saved;
    return route.fulfill({ json: saved });
  });
  return { page, state };
}

async function signup(page) {
  await page.goto(`${root}/sign-up?signed=0`);
  await page.getByRole('textbox', { name: 'Email address' }).fill('fixture@example.invalid');
  await page.getByRole('textbox', { name: 'Password', exact: true }).fill('Abcdefg1');
  await page.getByRole('textbox', { name: 'Name', exact: true }).fill('john bENEDICT');
  await page.getByRole('textbox', { name: 'Name', exact: true }).press('Enter');
  await page.getByRole('heading', { name: 'Verify your email', exact: true }).waitFor();
  await page.getByRole('textbox', { name: 'Verification code' }).fill('111111');
  await page.getByRole('button', { name: 'Verify email', exact: true }).click();
}

async function start(page, caller) {
  if (caller === 'signup') return signup(page);
  if (caller === 'onboarding') {
    await page.goto(`${root}/onboarding?signed=1`);
    await page.getByRole('heading', { name: 'Complete your profile', exact: true }).waitFor();
    await page.locator('#name').fill('Profile draft');
    return page.getByRole('button', { name: 'Continue', exact: true }).click();
  }
  await page.goto(`${root}/account?signed=1`);
  await page.getByRole('button', { name: 'Edit name', exact: true }).click();
  await page.locator('#name').fill('Profile draft');
  if (caller === 'name') return page.getByRole('button', { name: 'Save name', exact: true }).click();
  await page.getByRole('button', { name: 'Change', exact: true }).first().click();
  await page.getByRole('dialog', { name: /^(Save changes\?|Changes could not be saved)$/ }).getByRole('button', { name: 'Yes', exact: true }).click();
}

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      // The destination and success notification must wait for the profile write.
      for (const caller of ['name', 'onboarding', 'departure', 'signup']) {
        const { page, state } = await fixture(browser, viewport, errors, ['name', 'departure'].includes(caller));
        const gate = deferred(), requested = deferred();
        state.writes.push({ gate, requested });
        await start(page, caller);
        await waitForRequest(requested);
        assert.equal(state.trace.filter(item => item.startsWith('PUT:')).length, 1);
        assert.equal(await page.locator('[data-slot="toast"]').count(), 0);
        if (caller === 'name') {
          assert.equal(await page.getByRole('button', { name: 'Save name', exact: true }).isDisabled(), true);
          assert.equal(await page.locator('#name').inputValue(), 'Profile draft');
        } else if (caller === 'onboarding') {
          assert.equal(await page.getByRole('button', { name: 'Please wait...', exact: true }).isDisabled(), true);
          await page.getByRole('heading', { name: 'Complete your profile', exact: true }).waitFor();
        } else if (caller === 'departure') {
          assert.equal(new URL(page.url()).pathname, '/account');
          assert.equal(await page.getByRole('dialog', { name: /^(Save changes\?|Changes could not be saved)$/ }).getByRole('button', { name: 'Saving…', exact: true }).isDisabled(), true);
        } else {
          assert.deepEqual(state.trace, ['GET', 'PUT:John BENEDICT']);
          assert.equal(await page.getByRole('heading', { name: 'How would you like to receive alerts?', exact: true }).count(), 0);
        }
        gate.resolve();
        if (caller === 'name') {
          await page.getByText('Profile saved.', { exact: true }).waitFor();
          await page.getByRole('button', { name: 'Edit name', exact: true }).waitFor();
          assert.equal(await page.locator('#name').getAttribute('readonly'), '');
        } else if (caller === 'departure') {
          await page.getByRole('heading', { name: 'Email change is unavailable', exact: true }).waitFor();
          await page.getByText('Changes saved.', { exact: true }).waitFor();
        } else {
          await page.getByRole('heading', { name: 'How would you like to receive alerts?', exact: true }).waitFor();
          assert.equal(await page.locator('[data-slot="toast"]').count(), 0);
          if (caller === 'signup') assert.deepEqual(state.trace, ['GET', 'PUT:John BENEDICT', 'GET']);
        }
        assert.equal(state.tokens.filter(item => item.endsWith(':fresh')).length, 1);
        await page.close();
      }

      // Onboarding field errors keep the draft and retry the same profile operation.
      const onboarding = await fixture(browser, viewport, errors, false);
      onboarding.state.writes.push({ field: 'Profile name rejected.' });
      await start(onboarding.page, 'onboarding');
      await onboarding.page.locator('#name-error').getByText('Profile name rejected.', { exact: true }).waitFor();
      assert.equal(await onboarding.page.locator('#name').inputValue(), 'Profile draft');
      assert.equal(await onboarding.page.locator('[data-slot="toast"]').count(), 0);
      await onboarding.page.getByRole('button', { name: 'Continue', exact: true }).click();
      await onboarding.page.getByRole('heading', { name: 'How would you like to receive alerts?', exact: true }).waitFor();
      assert.deepEqual(onboarding.state.trace, ['GET', 'PUT:Profile draft', 'PUT:Profile draft']);
      await onboarding.page.close();

      // A failed departure save stays in its dialog. Retry executes the held destination.
      const departure = await fixture(browser, viewport, errors);
      departure.state.writes.push({ failure: 'Departure profile save failed.' });
      await start(departure.page, 'departure');
      const dialog = departure.page.getByRole('dialog', { name: 'Changes could not be saved' });
      await dialog.waitFor();
      assert.equal(new URL(departure.page.url()).pathname, '/account');
      assert.equal(await departure.page.locator('#name').inputValue(), 'Profile draft');
      assert.equal(await departure.page.locator('[data-slot="toast"]').count(), 0);
      await dialog.getByRole('button', { name: 'Retry', exact: true }).click();
      await departure.page.getByRole('heading', { name: 'Email change is unavailable', exact: true }).waitFor();
      assert.deepEqual(departure.state.trace, ['GET', 'PUT:Profile draft', 'PUT:Profile draft']);
      await departure.page.close();

      // Signup retains its name after a failed write, but consumes it before the follow-up read.
      for (const failureStage of ['write', 'read']) {
        const { page, state } = await fixture(browser, viewport, errors, false);
        if (failureStage === 'write') state.writes.push({ failure: 'Signup profile write failed.' });
        else state.reads.push({}, { failure: 'Signup follow-up read failed.' });
        await signup(page);
        await page.getByText('Account settings unavailable', { exact: true }).waitFor();
        assert.deepEqual(state.trace, failureStage === 'write'
          ? ['GET', 'PUT:John BENEDICT'] : ['GET', 'PUT:John BENEDICT', 'GET']);
        await page.getByRole('button', { name: 'Try again', exact: true }).click();
        await page.getByRole('heading', { name: 'How would you like to receive alerts?', exact: true }).waitFor();
        assert.deepEqual(state.trace, failureStage === 'write'
          ? ['GET', 'PUT:John BENEDICT', 'GET', 'PUT:John BENEDICT', 'GET']
          : ['GET', 'PUT:John BENEDICT', 'GET', 'GET']);
        await page.close();
      }
      console.log(`PASS ${viewport.width}: all profile callers preserve pending, failure, retry, and continuation behavior`);
    }

    // Former-session successes and failures cannot reconcile, notify, or continue.
    for (const caller of ['name', 'onboarding', 'departure', 'signup']) {
      for (const failure of [false, true]) {
        const viewport = { width: 1440, height: 900 };
        const { page, state } = await fixture(browser, viewport, errors, ['name', 'departure'].includes(caller));
        const gate = deferred(), requested = deferred();
        state.writes.push({ gate, requested, ...(failure ? { failure: 'Former profile save failed.' } : {}) });
        await start(page, caller);
        await waitForRequest(requested);
        state.account = { ...baseline, displayName: 'Second reader', email: 'second@example.invalid' };
        await page.evaluate(userId => window.dispatchEvent(new CustomEvent('fixture:auth', {
          detail: { userId, sessionId: 'second-session' },
        })), failure ? 'second-user' : 'fixture-user');
        await page.locator('small').filter({ hasText: 'second@example.invalid' }).waitFor();
        const pathname = new URL(page.url()).pathname;
        const response = page.waitForResponse(value => value.request().method() === 'PUT');
        gate.resolve();
        await (await response).finished();
        await page.waitForTimeout(150); // Let the former response body and continuation settle.
        assert.equal(new URL(page.url()).pathname, pathname, `${caller}: former response must not navigate`);
        assert.equal(await page.locator('[data-slot="toast"]').count(), 0, `${caller}: former response must not notify`);
        assert.equal(await page.getByRole('dialog', { name: /^(Save changes\?|Changes could not be saved)$/ }).count(), 0);
        await page.locator('.settings-desktop-nav').getByRole('button', { name: 'Account', exact: true }).click();
        assert.equal(await page.locator('#name').inputValue(), 'Second reader', `${caller}: former response must not reconcile`);
        await page.close();
      }
    }
    assert.deepEqual(errors, []);
    console.log('PASS former-session profile successes and failures are ignored for all four callers');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
