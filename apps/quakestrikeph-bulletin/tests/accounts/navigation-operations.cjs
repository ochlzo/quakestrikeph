// Account navigation characterization. Only isolated Clerk/Backend fixtures are used.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const groups = ['destinations', 'departure', 'history', 'links', 'isolation'];
const selected = process.env.NAVIGATION_GROUP;
if (selected && !groups.includes(selected)) throw new Error(`Unknown navigation group: ${selected}`);
const baseline = { userId: 'fixture-user', displayName: 'Maria Santos', email: 'maria@example.invalid',
  phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, latitude: 13.21667, longitude: 123.51667, distanceKm: 50 };
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
async function waitForHeldWrite(signal) {
  let timer;
  try {
    await Promise.race([signal.promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('The departure write did not start.')), 10000);
    })]);
  } finally { clearTimeout(timer); }
}
async function finishResponse(pending) {
  const response = await pending;
  let timer;
  try {
    await Promise.race([response.finished(), new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`Response did not finish: ${response.url()}`)), 10000);
    })]);
  } finally { clearTimeout(timer); }
}
async function fixture(browser, viewport, errors) {
  const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  const state = { account: { ...baseline }, writes: [], reads: 0, replies: [] };
  await page.route('**/api/v1/account**', async route => {
    const request = route.request();
    if (request.method() === 'GET') {
      state.reads++;
      return route.fulfill({ json: { account: state.account, pending: null, nextStep: 'complete' } });
    }
    const previous = state.account, body = request.postDataJSON();
    const saved = { ...previous, ...body };
    state.writes.push({ path: new URL(request.url()).pathname, body });
    const reply = state.replies.shift();
    reply?.requested?.resolve();
    if (reply?.gate) await reply.gate.promise;
    if (reply?.failure) return route.fulfill({ status: 503, json: { error: { code: 'UNAVAILABLE', message: 'Departure save failed.' } } });
    if (state.account === previous) state.account = saved;
    return route.fulfill({ json: saved });
  });
  const open = async path => {
    await page.goto(`${root}${path}?signed=1`);
    await page.locator('.account-loading').waitFor({ state: 'detached' });
    await page.getByRole('heading', { name: path === '/account' ? 'Account settings' : 'Alert preferences', exact: true }).waitFor();
  };
  const navigate = label => page.locator(viewport.width <= 760 ? '.settings-mobile-tabs' : '.settings-desktop-nav')
    .getByRole(viewport.width <= 760 ? 'tab' : 'button', { name: label, exact: true }).click();
  const editName = async () => {
    await page.getByRole('button', { name: 'Edit name', exact: true }).click();
    await page.locator('#name').fill('Unsaved reader');
  };
  return { page, state, open, navigate, editName };
}
const dialog = page => page.getByRole('dialog', { name: /^(Save changes\?|Changes could not be saved)$/ });
async function discard(page) {
  await dialog(page).getByRole('button', { name: 'No, discard it', exact: true }).click();
}
async function shellSignOut(page, viewport) {
  if (viewport.width <= 760) {
    const trigger = page.getByRole('button', { name: 'Toggle sidebar', exact: true });
    if (await trigger.getAttribute('aria-expanded') === 'false') await trigger.click();
  }
  else await page.locator('[data-slot="sidebar-container"]').hover();
  await page.getByRole('button', { name: 'User menu', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Sign-out', exact: true }).click();
}
const calls = (page, method) => page.evaluate(method => window.clerkFixture.calls.filter(call => call.method === method), method);
async function destinations(f, viewport) {
  const { page, state, open, navigate } = f;
  await open('/alerts');
  const reads = state.reads;
  await page.getByRole('link', { name: /Within 50 km/ }).click();
  await page.getByRole('heading', { name: 'Alert location', exact: true }).waitFor();
  await navigate('Account');
  await page.getByRole('heading', { name: 'Account settings', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Change', exact: true }).first().click();
  await page.getByRole('heading', { name: 'Email change is unavailable', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Back to account settings', exact: true }).click();
  await page.getByRole('button', { name: 'Remove account', exact: true }).click();
  await page.getByRole('heading', { name: 'Account removal is unavailable', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Back to account settings', exact: true }).click();
  await page.getByRole('button', { name: 'Change password', exact: true }).click();
  await page.getByRole('heading', { name: 'Verify your identity again', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await page.getByRole('heading', { name: 'Account settings', exact: true }).waitFor();
  await navigate('Alert preferences');
  await page.getByRole('button', { name: 'Add number', exact: true }).click();
  await page.getByRole('heading', { name: 'Add your mobile number', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await page.getByRole('heading', { name: 'Account settings', exact: true }).waitFor();
  assert.equal(state.reads, reads, `${viewport.width}: local navigation must not reload the account`);
}
async function departure(f, viewport) {
  const { page, state, open, editName } = f;
  await open('/account');
  await editName();
  const nativeDialogs = [];
  const reject = async event => { nativeDialogs.push(event.message()); await event.dismiss(); };
  page.on('dialog', reject);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  page.off('dialog', reject);
  assert.deepEqual(nativeDialogs, ['Discard your unsaved changes?']);
  assert.equal((await calls(page, 'signOut')).length, 0);
  assert.equal(await dialog(page).count(), 0);
  await shellSignOut(page, viewport);
  await dialog(page).waitFor();
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#name').inputValue(), 'Unsaved reader');
  assert.equal((await calls(page, 'signOut')).length, 0);
  // Save failure must retain the shell sign-out destination for Retry.
  await shellSignOut(page, viewport);
  state.replies.push({ failure: true });
  await dialog(page).getByRole('button', { name: 'Yes', exact: true }).click();
  await page.getByRole('dialog', { name: 'Changes could not be saved' }).waitFor();
  assert.equal((await calls(page, 'signOut')).length, 0);
  const gate = deferred();
  state.replies.push({ gate });
  await page.evaluate(() => window.clerkFixture.queue('signOut', { defer: true }));
  await dialog(page).getByRole('button', { name: 'Retry', exact: true }).click();
  await dialog(page).getByRole('button', { name: 'Saving…', exact: true }).waitFor();
  assert.equal(await dialog(page).getByRole('button', { name: 'Saving…', exact: true }).isDisabled(), true);
  assert.equal((await calls(page, 'signOut')).length, 0);
  const response = page.waitForResponse(response => response.request().method() === 'PUT');
  gate.resolve();
  await finishResponse(response);
  await page.waitForFunction(() => window.clerkFixture.calls.some(call => call.method === 'signOut'));
  assert.deepEqual((await calls(page, 'signOut'))[0].args, { redirectUrl: '/' });
  assert.equal(state.writes.length, 2);
  await page.evaluate(() => window.clerkFixture.release('signOut'));
  await page.waitForURL(`${root}/`);
}
async function historyCases(f) {
  const { page, state, open, navigate, editName } = f;
  await open('/account');
  await navigate('Alert preferences');
  await page.goBack();
  await page.getByRole('heading', { name: 'Account settings', exact: true }).waitFor();
  await editName();
  await page.goForward();
  await dialog(page).waitFor();
  await page.waitForURL('**/account');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#name').inputValue(), 'Unsaved reader');
  await page.goForward();
  await dialog(page).waitFor();
  await page.waitForURL('**/account');
  await discard(page);
  await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
  assert.equal(state.writes.length, 0);
  await navigate('Account');
  await editName();
  await page.goBack();
  await dialog(page).waitFor();
  await page.waitForURL('**/account');
  state.replies.push({ failure: true });
  await dialog(page).getByRole('button', { name: 'Yes', exact: true }).click();
  await page.getByRole('dialog', { name: 'Changes could not be saved' }).waitFor();
  assert.equal(new URL(page.url()).pathname, '/account');
  await dialog(page).getByRole('button', { name: 'Retry', exact: true }).click();
  await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
  assert.equal(state.account.displayName, 'Unsaved reader');
  assert.equal(state.writes.length, 2);
  // History state carries routing metadata, never credentials or draft fields.
  const historyState = await page.evaluate(() => history.state);
  for (const key of ['password', 'code', 'displayName', 'latitude', 'draft', 'account']) assert.equal(key in historyState, false);
  await navigate('Account');
  await page.getByRole('button', { name: 'Change password', exact: true }).click();
  await page.getByRole('heading', { name: 'Verify your identity again', exact: true }).waitFor();
  await page.locator('#current-password').fill('Unsubmitted secret');
  await page.goBack();
  await page.getByRole('heading', { name: 'Account settings', exact: true }).waitFor();
  await page.goForward();
  await page.getByRole('heading', { name: 'Verify your identity again', exact: true }).waitFor();
  assert.equal(await page.locator('#current-password').inputValue(), '', 'History must restart sensitive proof with cleared credentials');
}
async function links(f) {
  const { page, state, open, editName } = f;
  await open('/account');
  await editName();
  // Observe exclusion rules without allowing browser default navigation or downloads.
  for (const config of [
    { href: '#fixture' }, { href: '/account' }, { href: '/alerts', target: '_blank' },
    { href: '/alerts', download: true }, { href: '/alerts', ctrlKey: true },
    { href: '/alerts', metaKey: true }, { href: '/alerts', shiftKey: true },
    { href: '/alerts', altKey: true }, { href: '/alerts', button: 1 },
  ]) {
    const prevented = await page.evaluate(config => {
      const anchor = document.createElement('a');
      anchor.href = config.href;
      if (config.target) anchor.target = config.target;
      if (config.download) anchor.download = '';
      document.body.append(anchor);
      let intercepted;
      anchor.addEventListener('click', event => { intercepted = event.defaultPrevented; event.preventDefault(); });
      anchor.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, ...config }));
      anchor.remove();
      return intercepted;
    }, config);
    assert.equal(prevented, false, `The workflow must preserve the link exclusion: ${JSON.stringify(config)}`);
    assert.equal(await dialog(page).count(), 0);
  }
  const beforeUnload = await page.evaluate(() => {
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  });
  assert.equal(beforeUnload, true);
  for (const href of ['/alerts/location', '/about', 'https://outside.invalid/destination']) {
    if (href.startsWith('https:')) await page.route('https://outside.invalid/**', route => route.fulfill({ contentType: 'text/html', body: '<h1>Fixture destination</h1>' }));
    await page.evaluate(href => {
      const anchor = document.createElement('a'); anchor.href = href; anchor.id = 'departure-link';
      anchor.textContent = 'Fixture departure'; document.body.append(anchor); anchor.click();
    }, href);
    await dialog(page).waitFor();
    assert.equal(new URL(page.url()).pathname, '/account');
    if (href === '/alerts/location') {
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#name').inputValue(), 'Unsaved reader');
      await page.locator('#departure-link').click();
    }
    await discard(page);
    await page.waitForURL(href.startsWith('https:') ? href : `${root}${href}`);
    assert.equal(state.writes.length, 0);
    if (href !== 'https://outside.invalid/destination') { await open('/account'); await editName(); }
  }
}
async function isolation(browser, viewport, errors) {
  for (const identity of ['user', 'session']) for (const failure of [false, true]) {
    const f = await fixture(browser, viewport, errors), { page, state, open, navigate } = f;
    const gate = deferred();
    console.log(`CHECK ${viewport.width}: delayed location departure ${identity}/${failure ? 'failure' : 'success'}`);
    try {
      await open('/alerts');
      await navigate('Alert location');
      await page.getByRole('button', { name: 'Edit', exact: true }).click();
      await page.locator('#distance').fill('250');
      await navigate('Account');
      const requested = deferred();
      state.replies.push({ gate, requested, failure });
      await dialog(page).getByRole('button', { name: 'Yes', exact: true }).click();
      await waitForHeldWrite(requested);
      // The PUT is held. Replace identity before releasing its response.
      state.account = { ...baseline, displayName: 'Second reader', email: 'second@example.invalid' };
      const newRead = page.waitForResponse(response => response.request().method() === 'GET' &&
        new URL(response.url()).pathname === '/api/v1/account');
      await page.evaluate(identity => window.dispatchEvent(new CustomEvent('fixture:auth', {
        detail: { userId: identity === 'user' ? 'second-user' : 'fixture-user', sessionId: 'second-session' },
      })), identity);
      await finishResponse(newRead);
      await page.getByText('Within 50 km', { exact: true }).waitFor();
      const pathname = new URL(page.url()).pathname;
      const response = page.waitForResponse(response => response.request().method() === 'PUT');
      gate.resolve();
      await finishResponse(response);
      await page.waitForTimeout(150); // Allow the old response body and continuation to settle.
      assert.equal(new URL(page.url()).pathname, pathname);
      assert.equal(await dialog(page).count(), 0);
      assert.equal(await page.locator('[data-slot="toast"]').count(), 0);
      assert.equal(state.account.distanceKm, 50);
    } finally { gate.resolve(); await page.close(); }
  }
}
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true }), errors = [];
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      for (const group of groups) {
        if (selected && selected !== group) continue;
        if (group === 'isolation') await isolation(browser, viewport, errors);
        else {
          const f = await fixture(browser, viewport, errors);
          try { await ({ destinations, departure, history: historyCases, links })[group](f, viewport); }
          finally { await f.page.close(); }
        }
        console.log(`PASS ${viewport.width}: navigation ${group}`);
      }
    }
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
