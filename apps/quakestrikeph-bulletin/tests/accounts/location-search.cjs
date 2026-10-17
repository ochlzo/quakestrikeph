// Start the account fixture server before running this browser regression check.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const account = { userId: 'fixture-user', displayName: 'Maria', email: 'maria@example.invalid',
  phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null };

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const viewport of [{ width: 1559, height: 884 }, { width: 390, height: 844 }, { width: 820, height: 600 }]) {
      for (const scroll of [0, 250]) {
        const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
        await page.route('**/api/v1/account**', route => route.fulfill({ json: { account, nextStep: 'complete' } }));
        await page.goto(`${root}/location?signed=1`);
        await page.getByRole('button', { name: 'Set location', exact: true }).click();
        await page.addStyleTag({ content: 'html { scroll-behavior: auto !important; }' });
        const input = page.getByRole('combobox', { name: 'Search for a location' });
        await input.waitFor();
        await page.evaluate(y => window.scrollTo(0, y), scroll);
        await input.click();
        for (const query of ['ala', 'zzzzz', 'Quezon']) {
          await input.fill(query);
          if (query === 'zzzzz') await page.locator('[data-slot="combobox-empty"]').waitFor();
          else await page.getByRole('option').first().waitFor();
          await page.waitForFunction(() => {
            const popup = document.querySelector('[data-slot="combobox-content"]');
            return popup && !popup.hasAttribute('data-entering');
          });
          const bounds = await page.evaluate(() => {
            const field = document.querySelector('.location-search-field').getBoundingClientRect();
            const popup = document.querySelector('[data-slot="combobox-content"]').getBoundingClientRect();
            const list = document.querySelector('[role="listbox"]');
            return { separate: popup.bottom <= field.top - 4 || popup.top >= field.bottom + 4,
              height: popup.height, aligned: Math.abs(popup.left - field.left) < 2,
              sameWidth: Math.abs(popup.width - field.width) < 2,
              scrollable: list.scrollHeight > list.clientHeight,
              overflow: document.documentElement.scrollWidth > innerWidth };
          });
          assert.ok(bounds.separate, 'Suggestions must not cover the search field');
          assert.ok(bounds.height <= 288.1, 'Suggestions must respect the height limit');
          assert.ok(bounds.aligned && bounds.sameWidth && !bounds.overflow);
          if (query === 'ala') assert.ok(bounds.scrollable);
          if (query === 'zzzzz') {
            assert.equal(await page.locator('[data-slot="combobox-item"]').count(), 0);
            assert.match(await page.locator('[data-slot="combobox-empty"]').innerText(), /Try another name or use the map/);
          }
        }
        await input.press('ArrowDown');
        await input.press('Enter');
        await page.waitForFunction(() => document.querySelector('.location-summary').textContent.includes('Quezon'));
        await page.close();
        console.log(`PASS ${viewport.width}x${viewport.height}, scroll ${scroll}: placement, scrolling, empty state, recovery, keyboard selection`);
      }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
