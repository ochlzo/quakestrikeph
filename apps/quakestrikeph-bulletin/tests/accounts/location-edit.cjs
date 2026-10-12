// Run against the accounts Vite fixture; device replies and Backend writes are held explicitly.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const baseline = { userId: 'fixture-user', displayName: 'Maria', email: 'maria@example.invalid',
  phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, latitude: 13.21667, longitude: 123.51667, distanceKm: 50 };
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
async function waitForWrite(requested) {
  let timer;
  try {
    await Promise.race([requested.promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('The location write did not start.')), 10000);
    })]);
  } finally { clearTimeout(timer); }
}
async function fixture(browser, viewport, empty = false) {
  const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
  page.setDefaultTimeout(15000);
  const errors = [], writes = [];
  let account = empty ? { ...baseline, latitude: null, longitude: null, distanceKm: null } : { ...baseline };
  const state = { hold: null, fail: false, requested: deferred() };
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    window.deviceRequests = [];
    Object.defineProperty(navigator, 'geolocation', { configurable: true, value: {
      getCurrentPosition(success, failure) { window.deviceRequests.push({ success, failure }); },
    } });
  });
  await page.route('**/api/v1/account**', async route => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON();
      writes.push(body);
      state.requested.resolve();
      if (state.hold) await state.hold.promise;
      if (state.fail) return route.fulfill({ status: 503, json: { message: 'Location save unavailable' } });
      account = { ...account, ...body };
      return route.fulfill({ json: account });
    }
    return route.fulfill({ json: { account, nextStep: 'complete' } });
  });
  await page.goto(`${root}/alerts/location?signed=1`);
  await page.getByRole('button', { name: empty ? 'Set location' : 'Edit', exact: true }).click();
  const navigate = label => page.locator(viewport.width <= 760 ? '.settings-mobile-tabs' : '.settings-desktop-nav')
    .getByRole(viewport.width <= 760 ? 'tab' : 'button', { name: label, exact: true }).click();
  const reply = (index, failure = false, point = [14.6, 120.98]) => page.evaluate(({ index, failure, point }) => {
    const request = window.deviceRequests[index];
    if (failure) request.failure({ code: 1 });
    else request.success({ coords: { latitude: point[0], longitude: point[1] } });
  }, { index, failure, point });
  return { page, errors, writes, state, navigate, reply };
}

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      let f = await fixture(browser, viewport, true);
      try {
        const { page } = f;
        await page.locator('#distance').fill('0');
        await f.navigate('Account');
        await page.getByRole('dialog').getByRole('button', { name: 'Yes', exact: true }).click();
        await page.locator('[data-slot="dialog"]').waitFor({ state: 'hidden' });
        await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'combobox');
        assert.equal(await page.getByRole('combobox').evaluate(input => input === document.activeElement), true);
        await page.getByText('Choose a location using search or the map.', { exact: true }).waitFor();
        assert.equal(f.writes.length, 0);
        assert.deepEqual(f.errors, []);
      } finally { await f.page.close(); }

      f = await fixture(browser, viewport);
      try {
        const { page } = f;
        await page.locator('#distance').fill('0');
        await page.getByRole('button', { name: 'Use this location', exact: true }).click();
        await page.locator('#distance-error').waitFor();
        assert.equal(await page.locator('#distance').evaluate(input => input === document.activeElement), true);
        await page.locator('#distance').fill('100');
        await page.getByRole('button', { name: 'Use my location', exact: true }).click();
        const search = page.getByRole('combobox', { name: 'Search for a location' });
        await search.fill('Quezon');
        await page.getByRole('option').first().waitFor();
        await search.press('ArrowDown');
        await search.press('Enter');
        await page.waitForFunction(() => document.querySelector('.location-summary').textContent.includes('Quezon'));
        const selected = await page.locator('.location-summary').innerText();
        await f.reply(0);
        assert.equal(await page.locator('.location-summary').innerText(), selected);
        assert.equal(await page.getByRole('button', { name: 'Use my location', exact: true }).isEnabled(), true);

        await page.getByRole('button', { name: 'Use my location', exact: true }).click();
        await page.getByRole('button', { name: 'Use this location', exact: true }).click();
        await page.getByRole('button', { name: 'Edit', exact: true }).waitFor();
        assert.equal(await page.getByRole('button', { name: 'Edit', exact: true }).evaluate(button => button === document.activeElement), true);
        await page.getByRole('button', { name: 'Edit', exact: true }).click();
        await f.reply(1, true);
        assert.equal(await page.getByRole('button', { name: 'Use my location', exact: true }).isEnabled(), true);
        assert.equal(await page.locator('[data-slot="toast"]').count(), 0);
        assert.equal(await page.locator('#distance').inputValue(), '100');
        assert.deepEqual(f.errors, []);
      } finally { await f.page.close(); }

      f = await fixture(browser, viewport);
      try {
        const { page, state } = f;
        await page.locator('#distance').fill('100');
        await page.getByRole('button', { name: 'Use my location', exact: true }).click();
        await f.navigate('Account');
        await page.getByRole('dialog').waitFor();
        const previous = await page.locator('.location-summary').innerText();
        await f.reply(0);
        await page.waitForFunction(previous => document.querySelector('.location-summary').innerText !== previous, previous);
        const selected = await page.locator('.location-summary').innerText();
        await page.keyboard.press('Escape');
        await page.locator('[data-slot="dialog"]').waitFor({ state: 'hidden' });
        await page.getByRole('button', { name: 'Use my location', exact: true }).click();
        await f.navigate('Account');
        state.hold = deferred();
        state.fail = true;
        await page.getByRole('dialog').getByRole('button', { name: 'Yes', exact: true }).click();
        await waitForWrite(state.requested);
        await f.reply(1, false, [10.3, 123.9]);
        assert.equal(await page.locator('.location-summary').innerText(), selected);
        assert.equal(f.writes[0].latitude, 14.6);
        assert.equal(f.writes[0].distanceKm, 100);
        state.hold.resolve();
        const failure = page.getByRole('dialog', { name: 'Changes could not be saved' });
        await failure.waitFor();
        assert.equal(await page.locator('#distance').inputValue(), '100');
        assert.equal(await page.locator('[data-slot="toast"]').count(), 0);
        state.fail = false;
        await failure.getByRole('button', { name: 'Retry', exact: true }).click();
        await page.locator('.account-app[data-screen="account"]').waitFor();
        assert.deepEqual(f.writes[1], f.writes[0]);
        assert.deepEqual(f.errors, []);
      } finally { f.state.hold?.resolve(); await f.page.close(); }

      f = await fixture(browser, viewport);
      try {
        const { page } = f;
        await page.getByRole('button', { name: 'Use my location', exact: true }).click();
        await f.navigate('Account');
        await page.locator('.account-app[data-screen="account"]').waitFor();
        await f.reply(0, true);
        assert.equal(await page.locator('[data-slot="toast"]').count(), 0);
        await f.navigate('Alert location');
        await page.getByRole('button', { name: 'Edit', exact: true }).click();
        assert.equal(await page.getByRole('button', { name: 'Use my location', exact: true }).isEnabled(), true);
        assert.equal(await page.locator('#distance').inputValue(), '50');
        assert.deepEqual(f.errors, []);
      } finally { await f.page.close(); }

      f = await fixture(browser, viewport);
      try {
        const { page } = f;
        await page.locator('.location-map[data-map-ready="true"]').waitFor({ timeout: 45000 });
        await page.getByRole('button', { name: 'Use my location', exact: true }).click();
        const marker = page.locator('.maplibregl-marker');
        await marker.scrollIntoViewIfNeeded();
        const box = await marker.boundingBox();
        assert.ok(box, 'The real MapLibre pin must be visible');
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        await page.mouse.down();
        await page.mouse.move(box.x + box.width / 2 + 35, box.y + box.height / 2 + 20, { steps: 10 });
        await page.mouse.up();
        await page.getByRole('button', { name: 'Use my location', exact: true }).waitFor();
        await f.reply(0);
        await page.getByRole('button', { name: 'Use this location', exact: true }).click();
        await page.getByRole('button', { name: 'Edit', exact: true }).waitFor();
        await waitForWrite(f.state.requested);
        assert.ok(f.writes[0].latitude !== baseline.latitude || f.writes[0].longitude !== baseline.longitude,
          'Dragging must change the committed pin');
        assert.notEqual(f.writes[0].latitude, 14.6, 'A late device reply must not replace the dragged pin');
        await page.screenshot({ path: require('node:path').join(require('node:os').tmpdir(), `location-edit-map-${viewport.width}.png`) });
        assert.deepEqual(f.errors, []);
      } finally { await f.page.close(); }
      console.log(`PASS ${viewport.width}: validation focus, newer pin, reopened edit, held departure, retry, and screen disposal`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
