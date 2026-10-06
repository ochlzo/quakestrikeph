// Start the account fixture server before running this browser regression check.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const account = { userId: 'fixture-user', displayName: 'Maria', email: 'maria@example.invalid',
  phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, latitude: 13.21667, longitude: 123.51667, distanceKm: 50 };

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const viewport of [{ width: 1559, height: 884 }, { width: 384, height: 824 }]) {
      for (const reducedMotion of ['no-preference', 'reduce']) {
        const page = await browser.newPage({ viewport, reducedMotion });
        let reads = 0;
        await page.route('**/api/v1/account**', route => {
          reads++;
          return route.fulfill({ json: { account, nextStep: 'complete' } });
        });
        await page.goto(`${root}/alerts?signed=1`);
        await page.locator('#magnitude').fill('5');
        for (const [screen, label, index] of [['location', 'Alert location', 1], ['preferences', 'Alert preferences', 0], ['account', 'Account', 2], ['preferences', 'Alert preferences', 0]]) {
          if (screen === 'account') {
            assert.equal(await page.locator('#magnitude').inputValue(), '5', 'Switching settings must preserve the draft');
            await page.locator('#magnitude').fill('4.5');
          }
          const nav = page.locator(viewport.width <= 760 ? '.settings-mobile-tabs' : '.settings-desktop-nav');
          await nav.getByRole(viewport.width <= 760 ? 'tab' : 'button', { name: label, exact: true }).click();
          await page.locator(`.account-app[data-screen="${screen}"]`).waitFor();
          const motion = await page.evaluate(() => {
            const mobile = innerWidth <= 760;
            const nav = document.querySelector(mobile ? '.settings-mobile-tabs [data-slot="tabs-list"]' : '.settings-desktop-nav');
            const indicator = getComputedStyle(nav, '::before');
            const content = getComputedStyle(document.querySelector('.screen-focus'));
            return { content: content.animationName, duration: content.animationDuration,
              indicator: indicator.animationName, transition: indicator.transitionDuration };
          });
          assert.equal(motion.content, reducedMotion === 'reduce' ? 'none' : 'auth-field-entry');
          assert.equal(motion.duration, reducedMotion === 'reduce' ? '0s' : '0.32s');
          assert.equal(motion.transition, reducedMotion === 'reduce' ? '0s' : '0.32s');
          if (reducedMotion === 'reduce') assert.equal(motion.indicator, 'none');
          await page.waitForFunction(index => {
            const mobile = innerWidth <= 760;
            const nav = document.querySelector(mobile ? '.settings-mobile-tabs [data-slot="tabs-list"]' : '.settings-desktop-nav');
            const style = getComputedStyle(nav, '::before');
            const matrix = new DOMMatrix(style.transform);
            const expected = index * (mobile ? parseFloat(style.width) : parseFloat(style.height) + 8);
            return Math.abs((mobile ? matrix.m41 : matrix.m42) - expected) < 0.5;
          }, index);
        }
        assert.equal(reads, 1, 'Tab transitions must not reload account data');
        await page.close();
        console.log(`PASS ${viewport.width}x${viewport.height}, ${reducedMotion}: indicator, content, draft, requests`);
      }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
