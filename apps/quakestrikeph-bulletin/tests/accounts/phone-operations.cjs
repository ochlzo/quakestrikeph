// Isolated phone workflow checks. No live Clerk, SMS, or account requests.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const baseline = {
  userId: 'fixture-user', displayName: 'Maria Santos', email: 'maria@example.invalid',
  phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null,
};
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
async function requested(signal, message = 'The phone request did not start.') {
  let timer;
  try {
    await Promise.race([signal.promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(message)), 10000);
    })]);
  } finally { clearTimeout(timer); }
}
const pending = (id = 'attempt-1') => ({ id, phone: '+639171234567',
  expiresAt: new Date(Date.now() + 300000).toISOString(), resendAt: new Date(Date.now() - 1000).toISOString() });

async function fixture(browser, viewport, errors, account = baseline, attempt = null) {
  const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  const state = { account: { ...account }, pending: attempt, trace: [], replies: new Map() };
  const enqueue = (key, reply) => {
    if (!state.replies.has(key)) state.replies.set(key, []);
    state.replies.get(key).push(reply);
  };
  await page.route('**/api/v1/account**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace('/api/v1/account', '');
    const key = `${request.method()} ${path}`, body = request.postDataJSON();
    state.trace.push({ key, body });
    const reply = state.replies.get(key)?.shift();
    const previous = state.account, previousPending = state.pending;
    // Starting replacement can pause SMS even when sending the code fails.
    if (key === 'POST /phone/attempts' && previous.phone) state.account = { ...previous, smsEnabled: false };
    const destination = state.account;
    if (reply?.requested) reply.requested.resolve();
    if (reply?.gate) await reply.gate.promise;
    if (reply?.failure) return route.fulfill({ status: reply.status ?? 503, json: { error: {
      code: reply.code ?? 'UNAVAILABLE', message: reply.failure, ...(reply.field ? { field: reply.field } : {}),
    } } });
    if (key === 'GET ') return route.fulfill({ json: { account: previous, pending: previousPending,
      nextStep: previous.onboardingCompleted ? 'complete' : 'channels' } });
    if (key === 'POST /phone/attempts') {
      const next = pending(`attempt-${state.trace.filter(item => item.key === key).length}`);
      if (state.account === destination) state.pending = next;
      return route.fulfill({ json: next });
    }
    if (key === 'POST /phone/verify') {
      assert.equal(body.attemptId, previousPending.id);
      const next = { ...previous, phone: previousPending.phone, smsEnabled: false };
      if (state.account === previous) { state.account = next; state.pending = null; }
      return route.fulfill({ json: next });
    }
    if (key === 'DELETE /phone/attempts') {
      if (state.pending === previousPending) state.pending = null;
      return route.fulfill({ status: 204 });
    }
    assert.equal(key, 'PUT /preferences');
    const next = { ...previous, ...body, onboardingCompleted: true };
    if (state.account === previous) state.account = next;
    return route.fulfill({ json: next });
  });
  return { page, state, enqueue };
}
async function entry(page, replacement = false) {
  await page.goto(`${root}/account/phone?signed=1`);
  if (replacement) {
    await page.getByRole('textbox', { name: 'Current password', exact: true }).fill('fixture-password');
    await page.getByRole('button', { name: 'Verify identity', exact: true }).click();
  }
  await page.getByRole('heading', { name: replacement ? 'Change your mobile number' : 'Add your mobile number', exact: true }).waitFor();
}
async function send(page) {
  await page.locator('#phone').fill('09171234567');
  await page.getByRole('button', { name: 'Send verification code', exact: true }).click();
}
async function verify(page) {
  await page.locator('#code').fill('111111');
  await page.getByRole('button', { name: 'Verify code', exact: true }).click();
}
async function onboarding(page) {
  await page.goto(`${root}/onboarding?signed=1`);
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await send(page);
  await page.getByRole('heading', { name: 'Verify your mobile number', exact: true }).waitFor();
}
async function idle(page) {
  await page.waitForFunction(() => document.querySelector('.screen-focus')?.getAttribute('aria-busy') === 'false');
}

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      // First sign-in retains the account island; enrollment must adopt the authenticated session.
      for (const onboarding of [true, false]) {
        const { page, state } = await fixture(browser, viewport, errors, {
          ...baseline, onboardingCompleted: !onboarding,
        });
        await page.goto(`${root}/sign-in?signed=0`);
        await page.getByRole('textbox', { name: 'Email address' }).fill('maria@example.invalid');
        await page.getByRole('textbox', { name: 'Password', exact: true }).fill('fixture-password');
        await page.getByRole('button', { name: 'Sign in', exact: true }).click();
        await page.getByRole('heading', { name: 'Verify your email', exact: true }).waitFor();
        await page.getByRole('textbox', { name: 'Verification code' }).fill('111111');
        await page.getByRole('button', { name: 'Verify email', exact: true }).click();
        if (onboarding) {
          await page.getByRole('heading', { name: 'How would you like to receive alerts?', exact: true }).waitFor();
          await page.getByRole('button', { name: 'Continue', exact: true }).click();
        } else {
          await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
          await page.getByRole('button', { name: 'Add number', exact: true }).click();
        }
        await page.getByRole('heading', { name: 'Add your mobile number', exact: true }).waitFor();
        await send(page);
        await page.getByRole('heading', { name: 'Verify your mobile number', exact: true }).waitFor();
        assert.equal(state.account.smsEnabled, false, 'Sending a code must not enable SMS');
        await verify(page);
        await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
        await idle(page);
        assert.equal(state.account.smsEnabled, onboarding);
        assert.deepEqual(state.trace.map(item => item.key), onboarding
          ? ['GET ', 'PUT /preferences', 'POST /phone/attempts', 'POST /phone/verify', 'PUT /preferences']
          : ['GET ', 'POST /phone/attempts', 'POST /phone/verify']);
        await page.close();
      }
      console.log(`PASS ${viewport.width}: first sign-in, channel confirmation, and SMS enrollment`);
      // Replacement refresh runs after both sending outcomes, with independent refresh failures.
      for (const sendFails of [false, true]) for (const refreshFails of [false, true]) {
        const { page, state, enqueue } = await fixture(browser, viewport, errors, {
          ...baseline, phone: '+639181234567', smsEnabled: true,
        });
        await entry(page, true);
        if (sendFails) enqueue('POST /phone/attempts', { failure: 'Sending failed.' });
        if (refreshFails) enqueue('GET ', { failure: 'Refreshing failed.' });
        await send(page);
        if (refreshFails) await page.getByText('Account settings unavailable', { exact: true }).waitFor();
        else if (sendFails) await page.getByText('Sending failed.', { exact: true }).waitFor();
        else await page.getByRole('heading', { name: 'Verify your mobile number', exact: true }).waitFor();
        await idle(page);
        assert.deepEqual(state.trace.map(item => item.key), ['GET ', 'POST /phone/attempts', 'GET ']);
        assert.equal(state.account.phone, '+639181234567');
        assert.equal(state.account.smsEnabled, false);
        if (refreshFails && sendFails) assert.equal(await page.getByText('Refreshing failed.', { exact: true }).count(), 0);
        if (!sendFails && !refreshFails) {
          enqueue('POST /phone/verify', { failure: 'That code did not work.', status: 400, code: 'INVALID_CODE', field: 'code' });
          await verify(page);
          await page.locator('#code-error').getByText('That code did not work.', { exact: true }).waitFor();
          await verify(page);
          await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
          assert.equal(await page.getByRole('switch', { name: 'SMS alerts', exact: true }).isChecked(), false);
          assert.equal(state.trace.filter(item => item.key === 'PUT /preferences').length, 0);
          await page.getByText('Mobile number verified.', { exact: true }).waitFor();
          assert.equal(await page.getByText('SMS alerts enabled.', { exact: true }).count(), 0);
        }
        await page.close();
      }

      // Both deletion operations retain the attempt on failure and only continue after success.
      for (const operation of ['Use another number', 'Continue without SMS']) {
        const { page, state, enqueue } = await fixture(browser, viewport, errors, baseline, pending());
        await page.goto(`${root}/account/phone?signed=1`);
        enqueue('DELETE /phone/attempts', { failure: 'Deleting failed.' });
        await page.getByRole('button', { name: operation, exact: true }).click();
        await page.getByText('Deleting failed.', { exact: true }).waitFor();
        assert.equal(state.pending.id, 'attempt-1');
        await page.getByRole('heading', { name: 'Verify your mobile number', exact: true }).waitFor();
        const gate = deferred(), signal = deferred();
        enqueue('DELETE /phone/attempts', { gate, requested: signal });
        await page.getByRole('button', { name: operation, exact: true }).click();
        await requested(signal);
        await page.getByRole('heading', { name: 'Verify your mobile number', exact: true }).waitFor();
        gate.resolve();
        await page.getByRole('heading', { name: operation === 'Use another number' ? 'Add your mobile number' : 'Alert preferences', exact: true }).waitFor();
        assert.equal(state.pending, null);
        await page.close();
      }

      // Resend failures retain the code and attempt. Backend expiry starts phone entry again.
      const resend = await fixture(browser, viewport, errors, baseline, pending());
      await resend.page.goto(`${root}/account/phone?signed=1`);
      await resend.page.locator('#code').fill('123456');
      resend.enqueue('POST /phone/attempts', { failure: 'Resending failed.' });
      await resend.page.getByRole('button', { name: 'Resend code', exact: true }).click();
      await resend.page.getByText('Resending failed.', { exact: true }).waitFor();
      assert.equal(await resend.page.locator('#code').inputValue(), '123456');
      assert.equal(resend.state.pending.id, 'attempt-1');
      await resend.page.getByRole('button', { name: 'Resend code', exact: true }).click();
      await resend.page.getByText('A new SMS code was requested.', { exact: true }).waitFor();
      assert.equal(await resend.page.locator('#code').inputValue(), '');
      resend.enqueue('POST /phone/verify', { failure: 'The attempt expired.', status: 400, code: 'ATTEMPT_EXPIRED' });
      await verify(resend.page);
      await resend.page.getByRole('heading', { name: 'Add your mobile number', exact: true }).waitFor();
      await resend.page.close();

      // Back retains an attempt without sending DELETE. A direct visit resumes it.
      const back = await fixture(browser, viewport, errors, baseline, pending());
      await back.page.goto(`${root}/account/phone?signed=1`);
      await back.page.getByRole('button', { name: 'Back', exact: true }).click();
      await back.page.getByRole('heading', { name: 'Account settings', exact: true }).waitFor();
      assert.equal(back.state.trace.filter(item => item.key.startsWith('DELETE')).length, 0);
      await back.page.goto(`${root}/account/phone?signed=1`);
      await back.page.getByRole('heading', { name: 'Verify your mobile number', exact: true }).waitFor();
      await back.page.close();

      // A phone can remain verified after opt-in fails; the existing SMS switch retries opt-in.
      const optIn = await fixture(browser, viewport, errors, { ...baseline, onboardingCompleted: false });
      await onboarding(optIn.page);
      const optInGate = deferred(), optInRequested = deferred();
      optIn.enqueue('PUT /preferences', { failure: 'Opt-in failed.', gate: optInGate, requested: optInRequested });
      await verify(optIn.page);
      await requested(optInRequested);
      await optIn.page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      const emailSaved = optIn.page.waitForResponse(response => response.request().method() === 'PUT' && response.request().postDataJSON().emailEnabled);
      await optIn.page.getByRole('switch', { name: 'Email alerts', exact: true }).press('Space');
      await optIn.page.waitForTimeout(500);
      assert.equal(optIn.state.trace.filter(item => item.key === 'PUT /preferences').length, 2);
      optInGate.resolve();
      await optIn.page.getByText('Opt-in failed.', { exact: true }).waitFor();
      await (await emailSaved).finished();
      await idle(optIn.page);
      assert.equal(await optIn.page.getByText('Mobile number verified.', { exact: true }).count(), 1);
      assert.equal(await optIn.page.getByText('SMS alerts could not be enabled.', { exact: true }).count(), 1);
      assert.equal(await optIn.page.locator('[data-slot="toast"]').count(), 2, 'Each phase reports once');
      assert.equal(optIn.state.account.phone, '+639171234567');
      assert.equal(optIn.state.pending, null);
      assert.equal(optIn.state.account.emailEnabled, true, 'A newer email edit survives the failed SMS revision');
      const sms = optIn.page.getByRole('switch', { name: 'SMS alerts', exact: true });
      assert.equal(await sms.isChecked(), false);
      const retrySaved = optIn.page.waitForResponse(response => response.request().method() === 'PUT');
      await sms.press('Space');
      await (await retrySaved).finished();
      assert.equal(optIn.state.account.smsEnabled, true);
      assert.equal(optIn.state.trace.filter(item => item.key === 'POST /phone/verify').length, 1);
      await optIn.page.close();

      // Changing the proposed number retains onboarding intent; skipping clears it after deletion succeeds.
      for (const operation of ['Use another number', 'Continue without SMS']) {
        const { page, state, enqueue } = await fixture(browser, viewport, errors, { ...baseline, onboardingCompleted: false });
        await onboarding(page);
        enqueue('DELETE /phone/attempts', { failure: 'Onboarding deletion failed.' });
        await page.getByRole('button', { name: operation, exact: true }).click();
        await page.getByText('Onboarding deletion failed.', { exact: true }).waitFor();
        assert.ok(state.pending);
        await page.getByRole('button', { name: operation, exact: true }).click();
        if (operation === 'Continue without SMS') {
          await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
          await page.getByRole('button', { name: 'Add number', exact: true }).click();
        }
        await page.getByRole('heading', { name: 'Add your mobile number', exact: true }).waitFor();
        await send(page);
        await verify(page);
        await page.getByText('Mobile number verified.', { exact: true }).waitFor();
        await idle(page);
        assert.equal(state.account.smsEnabled, operation === 'Use another number');
        assert.equal(state.trace.filter(item => item.key === 'PUT /preferences').length, operation === 'Use another number' ? 2 : 1);
        await page.close();
      }

      // Verification reports before a held opt-in. A later SMS-off edit suppresses the enabled claim.
      for (const superseded of [false, true]) {
        const { page, state, enqueue } = await fixture(browser, viewport, errors, { ...baseline, onboardingCompleted: false });
        await onboarding(page);
        const gate = deferred(), signal = deferred();
        enqueue('PUT /preferences', { gate, requested: signal });
        await verify(page);
        await requested(signal);
        await page.getByText('Mobile number verified.', { exact: true }).waitFor();
        assert.equal(await page.getByText('SMS alerts enabled.', { exact: true }).count(), 0);
        let offSaved;
        if (superseded) {
          offSaved = page.waitForResponse(response => response.request().method() === 'PUT' && response.request().postDataJSON().smsEnabled === false);
          await page.getByRole('switch', { name: 'SMS alerts', exact: true }).press('Space');
          await page.waitForTimeout(500);
          assert.equal(state.trace.filter(item => item.key === 'PUT /preferences').length, 2);
        }
        gate.resolve();
        await idle(page);
        if (superseded) await (await offSaved).finished();
        else await page.getByText('SMS alerts enabled.', { exact: true }).waitFor();
        assert.equal(state.account.smsEnabled, !superseded);
        assert.equal(await page.getByText('SMS alerts enabled.', { exact: true }).count(), superseded ? 0 : 1);
        await page.close();
      }

      // Backend-required proof stays in the existing Clerk flow and can retry sending.
      const proof = await fixture(browser, viewport, errors);
      await entry(proof.page);
      proof.enqueue('POST /phone/attempts', { failure: 'Verify identity again.', status: 403, code: 'REVERIFICATION_REQUIRED' });
      await send(proof.page);
      await proof.page.getByRole('heading', { name: 'Verify your identity again', exact: true }).waitFor();
      await proof.page.locator('#current-password').fill('fixture-password');
      await proof.page.getByRole('button', { name: 'Verify identity', exact: true }).click();
      await send(proof.page);
      await proof.page.getByRole('heading', { name: 'Verify your mobile number', exact: true }).waitFor();
      await proof.page.close();

      // Phase-specific errors retain the shared authorization and field handling.
      for (const code of ['REVERIFICATION_REQUIRED', 'SIGN_IN_REQUIRED', 'INVALID_PREFERENCE']) {
        const { page, state, enqueue } = await fixture(browser, viewport, errors, { ...baseline, onboardingCompleted: false });
        await onboarding(page);
        enqueue('PUT /preferences', { failure: `Opt-in ${code}.`, status: 403, code,
          ...(code === 'INVALID_PREFERENCE' ? { field: 'smsEnabled' } : {}) });
        await verify(page);
        await page.getByText('SMS alerts could not be enabled.', { exact: true }).waitFor();
        await page.locator('[data-slot="toast-description"]').getByText(`Opt-in ${code}.`, { exact: true }).waitFor();
        if (code === 'SIGN_IN_REQUIRED') {
          await page.getByText('Account settings unavailable', { exact: true }).waitFor();
          assert.equal(new URL(page.url()).pathname, '/sign-in');
        } else await page.getByRole('heading', { name: code === 'REVERIFICATION_REQUIRED'
          ? 'Verify your identity again' : 'Alert preferences', exact: true }).waitFor();
        assert.equal(state.account.phone, '+639171234567');
        assert.equal(state.account.smsEnabled, false);
        assert.equal(await page.locator('[data-slot="toast"]').count(), 2);
        await page.close();
      }

      // A resumed attempt's Backend timestamp controls resend availability.
      const cooling = await fixture(browser, viewport, errors, baseline, { ...pending(), resendAt: new Date(Date.now() + 4000).toISOString() });
      await cooling.page.goto(`${root}/account/phone?signed=1`);
      const coolingResend = cooling.page.locator('.phone-resend');
      assert.equal(await coolingResend.isDisabled(), true);
      assert.equal(cooling.state.trace.filter(item => item.key.startsWith('POST')).length, 0);
      await cooling.page.getByRole('button', { name: 'Resend code', exact: true }).waitFor();
      await cooling.page.getByRole('button', { name: 'Resend code', exact: true }).click();
      await cooling.page.getByText('A new SMS code was requested.', { exact: true }).waitFor();
      await cooling.page.close();
      console.log(`PASS ${viewport.width}: replacement refresh, invalid code, deletion retry, resend, expiry, Back, and opt-in recovery`);
    }

    // Phone responses from a former identity or same-user session cannot affect the new account.
    for (const operation of ['send', 'replacement-send', 'replacement-refresh', 'resend', 'verify', 'another', 'skip', 'opt-in']) for (const fails of [false, true]) {
      console.log(`CHECK former-session ${operation}: ${fails ? 'failure' : 'success'}`);
      const { page, state, enqueue } = await fixture(browser, { width: 1440, height: 900 }, errors,
        { ...baseline, onboardingCompleted: operation !== 'opt-in',
          ...(operation.startsWith('replacement') ? { phone: '+639181234567', smsEnabled: true } : {}) },
        ['resend', 'verify', 'another', 'skip'].includes(operation) ? pending() : null);
      if (operation === 'opt-in') await onboarding(page);
      else if (operation === 'send' || operation.startsWith('replacement')) await entry(page, operation.startsWith('replacement'));
      else await page.goto(`${root}/account/phone?signed=1`);
      const key = operation === 'replacement-refresh' ? 'GET ' : operation === 'opt-in' ? 'PUT /preferences' : operation === 'verify' ? 'POST /phone/verify'
        : ['another', 'skip'].includes(operation) ? 'DELETE /phone/attempts' : 'POST /phone/attempts';
      const gate = deferred(), signal = deferred();
      enqueue(key, { gate, requested: signal, ...(fails ? { failure: 'Former phone operation failed.' } : {}) });
      if (operation === 'send' || operation.startsWith('replacement')) await send(page);
      else if (['verify', 'opt-in'].includes(operation)) await verify(page);
      else await page.getByRole('button', { name: operation === 'resend' ? 'Resend code' : operation === 'another' ? 'Use another number' : 'Continue without SMS', exact: true }).click();
      await requested(signal);
      // Existing completed notifications may survive navigation; only new former-session notifications are forbidden.
      const existingToasts = await page.locator('[data-slot="toast-title"]').allTextContents();
      state.account = { ...baseline, displayName: 'Second reader', email: 'second@example.invalid' };
      state.pending = null;
      const newSession = page.waitForResponse(value => value.request().method() === 'GET');
      await page.evaluate(userId => window.dispatchEvent(new CustomEvent('fixture:auth', { detail: {
        userId, sessionId: 'second-session',
      } })), fails ? 'second-user' : 'fixture-user');
      await (await newSession).finished();
      await page.locator('.account-loading').waitFor({ state: 'detached' });
      await page.getByRole('heading', { name: operation === 'opt-in' ? 'Alert preferences' : 'Add your mobile number', exact: true }).waitFor();
      const pathname = new URL(page.url()).pathname;
      const response = page.waitForResponse(value => `${value.request().method()} ${new URL(value.url()).pathname.replace('/api/v1/account', '')}` === key);
      gate.resolve();
      const formerResponse = await response;
      // A 204 deletion response has no body to wait for.
      if (!key.startsWith('DELETE')) await requested({ promise: formerResponse.finished() }, 'The former phone response did not finish.');
      await page.waitForTimeout(150);
      assert.equal(new URL(page.url()).pathname, pathname, operation);
      assert.deepEqual(await page.locator('[data-slot="toast-title"]').allTextContents(), existingToasts, operation);
      if (operation === 'opt-in') await page.locator('.settings-desktop-nav').getByRole('button', { name: 'Account', exact: true }).click();
      else await page.getByRole('button', { name: 'Back', exact: true }).click();
      assert.equal(await page.locator('#name').inputValue(), 'Second reader', operation);
      assert.equal(await page.getByRole('dialog', { name: /Save changes\?|Changes could not be saved/ }).count(), 0);
      await page.close();
    }
    assert.deepEqual(errors, []);
    console.log('PASS former-session successes and failures for all five phone operations and SMS opt-in');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
