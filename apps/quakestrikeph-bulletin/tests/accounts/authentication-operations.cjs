// Run against the isolated accounts Vite fixture. No live Clerk or provider calls.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const group = process.env.AUTH_GROUP;
const account = {
  userId: 'fixture-user', displayName: 'Fixture Reader', email: 'fixture@example.invalid',
  phone: '+639171234567', onboardingCompleted: true, status: 'active',
  emailEnabled: false, smsEnabled: false, magnitude: 4.5, nearbyOnly: false,
  latitude: null, longitude: null, distanceKm: null,
};
const complete = { status: 'complete', createdSessionId: 'fixture-session' };
const queue = (page, method, reply) => page.evaluate(({ method, reply }) => window.clerkFixture.queue(method, reply), { method, reply });
const calls = page => page.evaluate(() => window.clerkFixture.calls);
const methods = async page => (await calls(page)).map(call => call.method);
const heading = (page, name) => page.getByRole('heading', { name, exact: true }).waitFor();
async function requestIdentityCode(page) {
  await page.getByRole('button', { name: 'Send verification code', exact: true }).click();
  await heading(page, 'Verify your identity again');
}
const button = (page, name) => page.getByRole('button', { name, exact: true }).click();
const toast = (page, text) => page.locator('[data-slot="toast"]').getByText(text, { exact: true }).waitFor();
async function fixture(browser, viewport, errors, query = 'signed=0') {
  const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  await page.clock.install();
  const state = { account: { ...account }, reads: 0 };
  await page.route('**/api/v1/account**', route => {
    assert.equal(route.request().method(), 'GET');
    state.reads++;
    return route.fulfill({ json: { account: state.account, pending: null, nextStep: 'complete' } });
  });
  await page.goto(`${root}/?${query}`);
  return { page, state };
}
async function credentials(page, signup = false) {
  if (signup) {
    await page.getByRole('tab', { name: 'Sign up', exact: true }).click();
    await page.locator('#name').fill('john bENEDICT');
  }
  await page.locator('#email').fill('fixture@example.invalid');
  await page.locator('#password').fill(signup ? 'Abcdefg1' : 'fixture-password');
}
async function emailCode(page, signup = false) {
  await credentials(page, signup);
  await button(page, signup ? 'Create account' : 'Sign in');
  await heading(page, 'Verify your email');
  await page.locator('#code').fill('111111');
}
async function recovery(page, step = 'request') {
  await button(page, 'Forgot password?');
  await page.locator('#email').fill('fixture@example.invalid');
  if (step === 'request') return;
  await button(page, 'Send recovery code');
  await heading(page, 'Check your email');
  await page.locator('#code').fill('111111');
  if (step === 'code') return;
  await button(page, 'Verify code');
  await heading(page, 'Choose a new password');
  await newPassword(page);
}
async function newPassword(page) {
  await page.locator('#new-password').fill('Abcdefg1');
  await page.locator('#confirm-password').fill('Abcdefg1');
}
async function password(page, passwordless = false) {
  await heading(page, 'Account settings');
  await button(page, passwordless ? 'Add password' : 'Change password');
  await requestIdentityCode(page);
  assert.equal(await page.locator('#current-password').count(), 0);
  await page.locator('#code').fill('111111');
  await button(page, 'Verify identity');
  await heading(page, passwordless ? 'Add password sign-in' : 'Change your password');
  assert.equal(await page.locator('#current-password').count(), 0);
  await newPassword(page);
}
async function delayed(page, method, start, reply = {}) {
  const offset = (await calls(page)).length;
  await queue(page, method, { ...reply, defer: true });
  await start();
  await page.waitForFunction(({ method, offset }) => window.clerkFixture.calls.slice(offset).some(call => call.method === method && !call.settled), { method, offset });
  return async () => {
    await page.evaluate(method => window.clerkFixture.release(method), method);
    await page.waitForFunction(({ method, offset }) => window.clerkFixture.calls.slice(offset).some(call => call.method === method && call.settled), { method, offset });
  };
}
async function entryChecks(browser, viewport, errors) {
  for (const signup of [false, true]) {
    const first = signup ? 'signUp.create' : 'signIn.create';
    const prepare = signup ? 'prepareEmailAddressVerification' : 'prepareSecondFactor';
    for (const stage of [first, prepare]) {
      const { page } = await fixture(browser, viewport, errors);
      await credentials(page, signup);
      const release = await delayed(page, stage, () => button(page, signup ? 'Create account' : 'Sign in'), { fail: true });
      assert.equal(await page.getByRole('button', { name: 'Please wait...', exact: true }).isDisabled(), true);
      assert.equal(await page.locator('[data-slot="toast"]').count(), 0);
      await release();
      await toast(page, signup ? 'Account creation unsuccessful' : 'Sign-in unsuccessful');
      assert.deepEqual(await methods(page), stage === first ? [first] : [first, prepare]);
      await page.locator('#password').fill(signup ? 'Abcdefg1' : 'fixture-password');
      await button(page, signup ? 'Create account' : 'Sign in');
      await heading(page, 'Verify your email');
      await page.close();
    }
    const { page, state } = await fixture(browser, viewport, errors);
    await emailCode(page, signup);
    await page.clock.fastForward(61000);
    await button(page, 'Resend code');
    await toast(page, 'A new email code was requested.');
    const proof = signup ? 'attemptEmailAddressVerification' : 'attemptSecondFactor';
    const release = await delayed(page, proof, () => button(page, 'Verify email'));
    assert.equal(state.reads, 0);
    await release();
    await heading(page, 'Alert preferences');
    assert.deepEqual((await methods(page)).slice(0, 5), [first, prepare, prepare, proof, 'setActive']);
    await page.close();
    for (const resend of [false, true]) {
      const retry = await fixture(browser, viewport, errors);
      await emailCode(retry.page, signup);
      if (resend) await retry.page.clock.fastForward(61000);
      await queue(retry.page, resend ? prepare : proof, { fail: true });
      await button(retry.page, resend ? 'Resend code' : 'Verify email');
      await toast(retry.page, resend ? 'This request could not be completed. Please try again.' : 'That code did not work. Check it or request a new code.');
      assert.equal(await retry.page.locator('#code').inputValue(), '111111');
      await button(retry.page, resend ? 'Resend code' : 'Verify email');
      if (resend) await toast(retry.page, 'A new email code was requested.');
      else await heading(retry.page, 'Alert preferences');
      await retry.page.close();
    }
  }
  for (const status of ['complete', 'needs_second_factor', 'needs_identifier']) {
    const { page } = await fixture(browser, viewport, errors);
    await credentials(page);
    await queue(page, 'signIn.create', { value: { ...complete, status } });
    await button(page, 'Sign in');
    if (status === 'complete') await heading(page, 'Alert preferences');
    else if (status === 'needs_second_factor') await heading(page, 'Verify your email');
    else {
      await toast(page, 'Sign-in unsuccessful');
      assert.equal((await methods(page)).includes('setActive'), false);
    }
    await page.close();
  }
  const missing = await fixture(browser, viewport, errors, 'signed=0&missing-factor=1');
  await credentials(missing.page);
  await button(missing.page, 'Sign in');
  await toast(missing.page, 'Sign-in unsuccessful');
  assert.deepEqual(await methods(missing.page), ['signIn.create']);
  await missing.page.close();
  const activation = await fixture(browser, viewport, errors);
  await emailCode(activation.page);
  await queue(activation.page, 'setActive', { fail: true });
  await button(activation.page, 'Verify email');
  await toast(activation.page, 'That code did not work. Check it or request a new code.');
  assert.equal(await activation.page.locator('#code').inputValue(), '');
  await activation.page.close();
  const google = await fixture(browser, viewport, errors);
  await button(google.page, 'Continue with Google');
  await toast(google.page, 'Google sign-in was not completed. Try again or use your password.');
  assert.deepEqual((await calls(google.page))[0].args, {
    strategy: 'oauth_google', redirectUrl: '/sso-callback', redirectUrlComplete: '/alerts', oidcPrompt: 'select_account',
  });
  await google.page.close();
}
async function recoveryChecks(browser, viewport, errors) {
  for (const fail of [false, true]) {
    const { page } = await fixture(browser, viewport, errors);
    await recovery(page);
    await queue(page, 'signIn.create', { fail });
    await button(page, 'Send recovery code');
    await heading(page, 'Check your email');
    assert.equal(await page.locator('[data-slot="toast"]').count(), 0);
    await page.clock.fastForward(61000);
    await queue(page, 'signIn.create', { fail });
    await button(page, 'Resend code');
    await toast(page, 'Recovery code requested, if available.');
    assert.deepEqual((await calls(page)).map(call => call.args), [
      { strategy: 'reset_password_email_code', identifier: 'fixture@example.invalid' },
      { strategy: 'reset_password_email_code', identifier: 'fixture@example.invalid' },
    ]);
    await page.close();
  }
  for (const step of ['code', 'reset']) {
    const { page } = await fixture(browser, viewport, errors);
    await recovery(page, step);
    const method = step === 'code' ? 'attemptFirstFactor' : 'resetPassword';
    const label = step === 'code' ? 'Verify code' : 'Save new password';
    const release = await delayed(page, method, () => button(page, label), { fail: true });
    await release();
    await toast(page, 'Recovery could not be completed. Check your code or request a new one.');
    await button(page, label);
    await heading(page, step === 'code' ? 'Choose a new password' : 'Alert preferences');
    if (step === 'reset') {
      assert.deepEqual((await calls(page)).find(call => call.method === 'resetPassword').args,
        { password: 'Abcdefg1', signOutOfOtherSessions: true });
    }
    await page.close();
  }
}
async function confirmationChecks(browser, viewport, errors) {
  for (const target of ['password', 'phone']) {
    const { page } = await fixture(browser, viewport, errors, `signed=1&initial=${target}`);
    await heading(page, 'Verify your identity');
    const initialCalls = await methods(page);
    assert.equal(initialCalls.includes('startVerification'), false);
    assert.equal(initialCalls.includes('prepareFirstFactorVerification'), false);
    assert.equal(await page.locator('#code').count(), 0);
    await page.getByText('To continue, we will send a verification code to f•••@example.invalid.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Resend code', exact: true }).count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    const buttonWidth = await page.getByRole('button', { name: 'Send verification code', exact: true }).evaluate(el => el.getBoundingClientRect().width);
    const formWidth = await page.locator('.screen-focus form').evaluate(el => el.getBoundingClientRect().width);
    assert.ok(Math.abs(buttonWidth - formWidth) < 1, 'Send button fills the form width');
    if (viewport.width > 760) assert.equal(formWidth, 440, 'Desktop verification uses a compact column');
    await page.screenshot({ path: `../../.impeccable/review/accounts/confirm-${target}-${viewport.width}.png` });
    await button(page, 'Back');
    await heading(page, 'Account settings');
    await page.getByRole('dialog', { name: 'Mobile number', exact: true }).waitFor({ state: 'hidden' });
    assert.deepEqual(await methods(page), initialCalls, 'Back must not send an OTP');
    if (target === 'password') await button(page, 'Change password');
    else {
      await page.locator('.account-row').filter({ hasText: 'Mobile number' }).getByRole('button', { name: 'Manage', exact: true }).click();
      await button(page, 'Change number');
    }
    await heading(page, 'Verify your identity');
    const release = await delayed(page, 'prepareFirstFactorVerification', () => button(page, 'Send verification code'), { fail: true });
    const sending = page.getByRole('button', { name: 'Sending...', exact: true });
    assert.equal(await sending.isDisabled(), true);
    assert.equal(await page.locator('.screen-focus form').getAttribute('aria-busy'), 'true');
    assert.equal(await sending.locator('svg').count(), 1);
    await release();
    await toast(page, 'This request could not be completed. Please try again.');
    await heading(page, 'Verify your identity');
    assert.equal(await page.locator('#code').count(), 0);
    await requestIdentityCode(page);
    await page.getByText('We sent a code to f•••@example.invalid.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: /Resend in/ }).isDisabled(), true);
    await page.close();
  }
}
async function sharedProofChecks(browser, viewport, errors) {
  for (const passwordless of [false, true]) {
    const { page } = await fixture(browser, viewport, errors, `signed=1&initial=account${passwordless ? '&passwordless=1' : ''}`);
    await page.clock.pauseAt(await page.evaluate(() => Date.now() + 1000));
    await password(page, passwordless);
    await button(page, 'Back');
    await heading(page, 'Account settings');
    await page.locator('.account-row').filter({ hasText: 'Mobile number' }).getByRole('button', { name: 'Manage', exact: true }).click();
    await page.getByRole('dialog', { name: 'Mobile number', exact: true }).waitFor();
    await button(page, 'Change number');
    await heading(page, 'Change your mobile number');
    assert.equal(await page.locator('#current-password').count(), 0);
    assert.equal((await methods(page)).filter(method => method === 'startVerification').length, 1);
    await button(page, 'Back');
    await heading(page, 'Account settings');
    await page.getByRole('dialog', { name: 'Mobile number', exact: true }).waitFor({ state: 'hidden' });
    await page.clock.fastForward(299999);
    await button(page, passwordless ? 'Add password' : 'Change password');
    await heading(page, passwordless ? 'Add password sign-in' : 'Change your password');
    await newPassword(page);
    await page.clock.fastForward(1);
    await button(page, 'Save password');
    await requestIdentityCode(page);
    assert.equal(await page.locator('#code').inputValue(), '');
    assert.equal((await methods(page)).includes('updatePassword'), false, 'Expiry while editing must block the password write');
    await page.locator('#code').fill('111111');
    await button(page, 'Verify identity');
    await heading(page, passwordless ? 'Add password sign-in' : 'Change your password');
    await button(page, 'Save password');
    await heading(page, 'Account settings');
    await page.close();
  }
  for (const changed of ['reload', 'session', 'user', 'signed-out']) {
    const { page } = await fixture(browser, viewport, errors, 'signed=1&initial=account');
    await password(page);
    if (changed === 'reload') {
      await page.reload();
      await heading(page, 'Change your password');
      assert.equal(await page.locator('#new-password').count(), 1);
      assert.equal((await methods(page)).includes('startVerification'), false, 'Refresh reuses Clerk verification age');
      await page.clock.fastForward(300000);
      await newPassword(page);
      await button(page, 'Save password');
      await heading(page, 'Verify your identity');
    } else {
      await page.evaluate(changed => window.dispatchEvent(new CustomEvent('fixture:auth', { detail: {
        userId: changed === 'signed-out' ? null : changed === 'user' ? 'another-user' : 'fixture-user',
        sessionId: changed === 'signed-out' ? null : 'another-session',
      } })), changed);
      await heading(page, changed === 'signed-out' ? 'Sign in' : 'Verify your identity');
    }
    assert.equal(await page.locator('#new-password').count(), 0);
    await page.close();
  }
  const phone = await fixture(browser, viewport, errors, 'signed=1&initial=phone');
  await phone.page.clock.pauseAt(await phone.page.evaluate(() => Date.now() + 1000));
  await requestIdentityCode(phone.page);
  await phone.page.locator('#code').fill('111111');
  await button(phone.page, 'Verify identity');
  await heading(phone.page, 'Change your mobile number');
  await phone.page.locator('#phone').fill('09171234567');
  let attempts = 0;
  await phone.page.route('**/api/v1/account/phone/attempts', route => {
    attempts++;
    return route.fulfill({ status: 503, json: { error: { code: 'UNAVAILABLE', message: 'Fixture SMS unavailable.' } } });
  });
  await phone.page.clock.fastForward(300000);
  await button(phone.page, 'Send code');
  await requestIdentityCode(phone.page);
  assert.equal(attempts, 0, 'Expired proof must not request an SMS');
  await phone.page.locator('#code').fill('111111');
  await button(phone.page, 'Verify identity');
  await heading(phone.page, 'Change your mobile number');
  await button(phone.page, 'Send code');
  await toast(phone.page, 'Fixture SMS unavailable.');
  assert.equal(attempts, 1);
  await phone.page.close();
}
async function credentialChecks(browser, viewport, errors) {
  for (const passwordless of [false, true]) {
    const { page } = await fixture(browser, viewport, errors, `signed=1&initial=account${passwordless ? '&passwordless=1' : ''}`);
    await password(page, passwordless);
    const release = await delayed(page, 'updatePassword', () => button(page, 'Save password'), { fail: true });
    await release();
    await toast(page, 'The password could not be saved. Try again or verify your email again. Use at least 8 characters, including one lowercase letter, one uppercase letter, and one number.');
    await button(page, 'Save password');
    await toast(page, 'Password saved.');
    await heading(page, 'Account settings');
    const trace = await calls(page);
    const proof = trace.findIndex(call => call.method === 'attemptFirstFactorVerification');
    assert.deepEqual(trace[proof].args, { strategy: 'email_code', code: '111111' });
    assert.equal(trace[proof + 1].method, 'getToken');
    assert.deepEqual(trace[proof + 1].args, { skipCache: true });
    assert.deepEqual(trace.find(call => call.method === 'updatePassword').args, {
      newPassword: 'Abcdefg1', signOutOfOtherSessions: true,
    });
    await button(page, passwordless ? 'Add password' : 'Change password');
    await heading(page, passwordless ? 'Add password sign-in' : 'Change your password');
    assert.equal((await methods(page)).filter(method => method === 'startVerification').length, 1,
      'Recent email proof is reused after a password change');
    await page.close();
  }
  const emailOnly = await fixture(browser, viewport, errors, 'signed=1&initial=account');
  await heading(emailOnly.page, 'Account settings');
  await queue(emailOnly.page, 'startVerification', { value: { supportedFirstFactors: [{ strategy: 'password' }] } });
  await button(emailOnly.page, 'Change password');
  await button(emailOnly.page, 'Send verification code');
  await toast(emailOnly.page, 'This request could not be completed. Please try again.');
  assert.deepEqual((await methods(emailOnly.page)).filter(method => method !== 'getToken'), ['startVerification']);
  await requestIdentityCode(emailOnly.page);
  await emailOnly.page.locator('#code').fill('222222');
  await button(emailOnly.page, 'Verify identity');
  await toast(emailOnly.page, 'Identity verification did not work. Check your password or code and try again.');
  assert.equal(await emailOnly.page.locator('#new-password').count(), 0);
  assert.equal((await methods(emailOnly.page)).includes('updatePassword'), false);
  await emailOnly.page.close();
  for (const method of ['startVerification', 'prepareFirstFactorVerification', 'attemptFirstFactorVerification', 'getToken']) {
    const { page } = await fixture(browser, viewport, errors, 'signed=1&initial=account&passwordless=1');
    await heading(page, 'Account settings');
    const entering = ['startVerification', 'prepareFirstFactorVerification'].includes(method);
    await button(page, 'Add password');
    if (!entering) {
      await requestIdentityCode(page);
      await page.locator('#code').fill('111111');
    }
    await queue(page, method, { fail: true });
    await button(page, entering ? 'Send verification code' : 'Verify identity');
    await page.locator('[data-slot="toast"]').waitFor();
    assert.equal(await page.getByRole('heading', { name: 'Add password sign-in', exact: true }).count(), 0);
    await button(page, entering ? 'Send verification code' : 'Verify identity');
    await page.getByRole('heading', { name: entering ? 'Verify your identity again' : 'Add password sign-in', exact: true }).waitFor();
    await page.close();
  }
  const resend = await fixture(browser, viewport, errors, 'signed=1&initial=account&passwordless=1');
  await button(resend.page, 'Add password');
  await requestIdentityCode(resend.page);
  await resend.page.clock.fastForward(61000);
  const count = (await methods(resend.page)).filter(method => method === 'startVerification').length;
  await button(resend.page, 'Resend code');
  await resend.page.waitForFunction(count => window.clerkFixture.calls.filter(call => call.method === 'startVerification').length > count, count);
  assert.equal(await resend.page.getByRole('button', { name: /Resend in/ }).isDisabled(), true);
  await resend.page.close();
  const missing = await fixture(browser, viewport, errors, 'signed=1&initial=account&passwordless=1&missing-factor=1');
  await button(missing.page, 'Add password');
  await button(missing.page, 'Send verification code');
  await toast(missing.page, 'This request could not be completed. Please try again.');
  assert.equal(await missing.page.getByRole('heading', { name: 'Verify your identity again', exact: true }).count(), 0);
  await missing.page.close();
  const incomplete = await fixture(browser, viewport, errors, 'signed=1&initial=account');
  await button(incomplete.page, 'Change password');
  await requestIdentityCode(incomplete.page);
  await incomplete.page.locator('#code').fill('111111');
  const offset = (await calls(incomplete.page)).length;
  await queue(incomplete.page, 'attemptFirstFactorVerification', { value: { status: 'unverified' } });
  await button(incomplete.page, 'Verify identity');
  await toast(incomplete.page, 'Identity verification did not work. Check your password or code and try again.');
  assert.deepEqual((await methods(incomplete.page)).slice(offset), ['attemptFirstFactorVerification']);
  await incomplete.page.close();
}
async function taskChecks(browser, viewport, errors) {
  for (const method of ['updatePassword', 'setActive']) {
    const { page } = await fixture(browser, viewport, errors, 'signed=1&task=reset-password');
    await heading(page, 'Choose a new password');
    await newPassword(page);
    await queue(page, method, { fail: true });
    await button(page, 'Save new password');
    await toast(page, 'The password could not be saved. Please try again.');
    assert.equal(new URL(page.url()).pathname, '/');
    const trace = await calls(page);
    assert.deepEqual(trace.filter(call => ['updatePassword', 'setActive'].includes(call.method)).map(call => call.method),
      method === 'updatePassword' ? ['updatePassword'] : ['updatePassword', 'setActive']);
    await newPassword(page);
    await button(page, 'Save new password');
    await page.waitForURL('**/alerts');
    await page.close();
  }
  for (const task of ['setup-mfa', 'choose-organization', 'unknown-task']) {
    const { page, state } = await fixture(browser, viewport, errors, `signed=1&task=${task}`);
    await heading(page, 'Complete account verification');
    assert.equal(state.reads, 0, 'Required tasks precede Backend account loading');
    const content = task === 'setup-mfa' ? 'Required multi-factor setup'
      : task === 'choose-organization' ? 'Required organization choice' : 'Please sign in again to complete account verification.';
    await page.getByText(content, { exact: true }).waitFor();
    await queue(page, 'signOut', { fail: true });
    await button(page, 'Return to sign in');
    await toast(page, 'Sign-out could not be completed. Please try again.');
    assert.deepEqual((await calls(page)).find(call => call.method === 'signOut').args, { redirectUrl: '/sign-in' });
    await button(page, 'Return to sign in');
    await page.waitForURL('**/sign-in');
    await page.close();
  }
  // The account row retains its native discard confirmation; the shell retains its dialog.
  for (const source of ['account', 'shell']) {
    if (source === 'shell' && viewport.width !== 1440) continue;
    const { page } = await fixture(browser, viewport, errors, 'signed=1&initial=account');
    await heading(page, 'Account settings');
    await button(page, 'Edit name');
    await page.locator('#name').fill('Unsaved reader');
    const requestSignOut = async () => {
      if (source === 'account') return button(page, 'Sign out');
      await button(page, 'User menu');
      await page.getByRole('menuitem', { name: 'Sign-out', exact: true }).click();
    };
    if (source === 'account') page.once('dialog', dialog => dialog.dismiss());
    await requestSignOut();
    if (source === 'shell') {
      await page.getByRole('dialog', { name: 'Save changes?', exact: true }).waitFor();
      await page.keyboard.press('Escape');
    }
    assert.equal((await methods(page)).includes('signOut'), false);
    await queue(page, 'signOut', { fail: true });
    if (source === 'account') page.once('dialog', dialog => dialog.accept());
    await requestSignOut();
    if (source === 'shell') await button(page, 'No, discard it');
    await toast(page, 'Sign-out could not be completed. Please try again.');
    assert.deepEqual((await calls(page)).find(call => call.method === 'signOut').args, { redirectUrl: '/' });
    await page.route(`${root}/`, route => route.fulfill({ contentType: 'text/html', body: '<h1>Public Bulletin</h1>' }));
    if (source === 'account') page.once('dialog', dialog => dialog.accept());
    await requestSignOut();
    await heading(page, 'Public Bulletin');
    await page.close();
  }
}
async function isolationChecks(browser, viewport, errors) {
  const entry = (method, signup = false) => ({ method, setup: page => credentials(page, signup), start: page => button(page, signup ? 'Create account' : 'Sign in') });
  const email = (method, signup = false, resend = false) => ({ method,
    setup: async page => { await emailCode(page, signup); if (resend) await page.clock.fastForward(61000); },
    start: page => button(page, resend ? 'Resend code' : 'Verify email'),
  });
  const recover = (method, step, resend = false) => ({ method,
    setup: async page => { await recovery(page, step); if (resend) await page.clock.fastForward(61000); },
    start: page => button(page, resend ? 'Resend code' : step === 'request' ? 'Send recovery code' : step === 'code' ? 'Verify code' : 'Save new password'),
  });
  const signed = 'signed=1&initial=account';
  const reverify = (method, resend = false) => ({ method, query: `${signed}&passwordless=1`,
    setup: async page => {
      await button(page, 'Add password'); await requestIdentityCode(page);
      await page.locator('#code').fill('111111'); if (resend) await page.clock.fastForward(61000);
    }, start: page => button(page, resend ? 'Resend code' : 'Verify identity'),
  });
  const scenarios = [
    entry('signIn.create'), entry('prepareSecondFactor'),
    entry('signUp.create', true), entry('prepareEmailAddressVerification', true),
    email('attemptSecondFactor'), email('attemptEmailAddressVerification', true),
    email('prepareSecondFactor', false, true), email('prepareEmailAddressVerification', true, true),
    recover('signIn.create', 'request'), recover('signIn.create', 'code', true),
    recover('attemptFirstFactor', 'code'), recover('resetPassword', 'reset'),
    { method: 'startVerification', query: signed, setup: async page => { await heading(page, 'Account settings'); await button(page, 'Change password'); }, start: page => button(page, 'Send verification code') },
    { method: 'prepareFirstFactorVerification', query: `${signed}&passwordless=1`, setup: async page => { await heading(page, 'Account settings'); await button(page, 'Add password'); }, start: page => button(page, 'Send verification code') },
    reverify('attemptFirstFactorVerification'), reverify('getToken'), reverify('prepareFirstFactorVerification', true),
    { method: 'updatePassword', query: signed, setup: page => password(page), start: page => button(page, 'Save password') },
    { method: 'updatePassword', query: 'signed=1&task=reset-password', setup: async page => { await heading(page, 'Choose a new password'); await newPassword(page); }, start: page => button(page, 'Save new password') },
  ];
  for (const scenario of scenarios) {
    for (const fail of [false, true]) {
      for (const identity of ['user', 'session']) {
        const { page, state } = await fixture(browser, viewport, errors, scenario.query);
        await scenario.setup(page);
        const release = await delayed(page, scenario.method, () => scenario.start(page), { fail });
        state.account = { ...account, displayName: 'Second reader', email: 'second@example.invalid' };
        const loaded = page.waitForResponse(response => response.request().method() === 'GET' && response.url().includes('/api/v1/account'));
        await page.evaluate(identity => window.dispatchEvent(new CustomEvent('fixture:auth', {
          detail: { userId: identity === 'user' ? 'second-user' : 'fixture-user', sessionId: 'second-session' },
        })), identity);
        await (await loaded).finished();
        await page.locator('.account-loading').waitFor({ state: 'detached' });
        const pathname = new URL(page.url()).pathname;
        if (pathname === '/account/password') await heading(page, 'Verify your identity');
        const before = await methods(page);
        await release();
        await page.waitForTimeout(100); // Allow the former operation's continuation to settle.
        const label = `${scenario.method} ${fail ? 'failure' : 'success'} after ${identity} change`;
        assert.equal(new URL(page.url()).pathname, pathname, `${label}: must not navigate`);
        assert.equal(await page.locator('[data-slot="toast"]').count(), 0, `${label}: must not notify`);
        assert.deepEqual(await methods(page), before, `${label}: must not submit follow-up provider calls`);
        await page.close();
      }
    }
    console.log(`PASS former-session ${scenario.method}`);
  }
}
async function reverificationRetryChecks(browser, viewport, errors) {
  for (const cancel of [false, true]) {
    const { page } = await fixture(browser, viewport, errors, 'signed=1&task=reset-password');
    await heading(page, 'Choose a new password');
    await newPassword(page);
    await queue(page, 'updatePassword', { reverify: true });
    const release = await delayed(page, 'reverification', () => button(page, 'Save new password'), { fail: cancel });
    assert.equal((await methods(page)).filter(method => method === 'updatePassword').length, 1);
    assert.equal(await page.locator('#new-password').inputValue(), 'Abcdefg1');
    if (!cancel) await queue(page, 'setActive', { defer: true });
    await release();
    if (cancel) {
      await toast(page, 'The password could not be saved. Please try again.');
      assert.equal((await methods(page)).includes('setActive'), false);
      assert.equal((await methods(page)).filter(method => method === 'updatePassword').length, 1);
    } else {
      await page.waitForFunction(() => window.clerkFixture.calls.some(call => call.method === 'setActive' && !call.settled));
      assert.deepEqual(await methods(page), ['updatePassword', 'reverification', 'updatePassword', 'setActive']);
      await page.evaluate(() => window.clerkFixture.release('setActive'));
      await page.waitForURL('**/alerts');
    }
    await page.close();
  }
  for (const phase of ['request', 'proof']) {
    for (const identity of ['user', 'session']) {
      const { page, state } = await fixture(browser, viewport, errors, 'signed=1&task=reset-password');
      await heading(page, 'Choose a new password');
      await newPassword(page);
      if (phase === 'proof') await queue(page, 'updatePassword', { reverify: true });
      const release = await delayed(page, phase === 'proof' ? 'reverification' : 'updatePassword',
        () => button(page, 'Save new password'), phase === 'request' ? { reverify: true } : {});
      state.account = { ...account, email: 'second@example.invalid' };
      const loaded = page.waitForResponse(response => response.request().method() === 'GET' && response.url().includes('/api/v1/account'));
      await page.evaluate(identity => window.dispatchEvent(new CustomEvent('fixture:auth', {
        detail: { userId: identity === 'user' ? 'second-user' : 'fixture-user', sessionId: 'second-session' },
      })), identity);
      await (await loaded).finished();
      await heading(page, 'Alert preferences');
      const before = await methods(page);
      await release();
      await page.waitForTimeout(100); // Let the SDK proof/retry continuation settle.
      assert.deepEqual(await methods(page), before, `${phase}/${identity}: must not open proof or retry a former password request`);
      assert.equal(await page.locator('[data-slot="toast"]').count(), 0);
      assert.equal(new URL(page.url()).pathname, '/alerts');
      await page.close();
    }
  }
}
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  try {
    const checks = { confirmation: confirmationChecks, entry: entryChecks, recovery: recoveryChecks, credentials: credentialChecks, 'shared-proof': sharedProofChecks, tasks: taskChecks, isolation: isolationChecks, reverification: reverificationRetryChecks };
    if (group) assert(group in checks, `Unknown authentication group: ${group}`);
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      for (const [name, check] of Object.entries(checks)) {
        if (group && group !== name) continue;
        if (name === 'isolation' && viewport.width !== 1440) continue;
        await check(browser, viewport, errors);
        console.log(`PASS ${viewport.width}: authentication ${name}`);
      }
    }
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
