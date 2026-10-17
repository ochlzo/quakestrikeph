// Run against the account fixture server with PUBLIC_CLERK_PUBLISHABLE_KEY=FIXTURE_ONLY.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4333';

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
      page.setDefaultTimeout(10000);
      await page.route('**/api/v1/account**', route => route.fulfill({ json: {
        account: { userId: 'fixture-user', displayName: 'Maria', email: 'maria@example.invalid',
          phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false,
          smsEnabled: false, magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null },
        pending: null, nextStep: 'complete',
      } }));
      await page.goto(`${root}/alerts?signed=1`, { waitUntil: 'domcontentloaded' });
      await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      await page.evaluate(async () => {
        const { toast } = await import('/src/components/ui/toast.tsx');
        toast.add({ title: 'Modal toast regression', timeout: 0 });
      });
      const toast = page.locator('[data-slot="toast"]').filter({ hasText: 'Modal toast regression' });
      await toast.waitFor();
      assert.equal(await toast.evaluate(node => Boolean(node.closest('[data-slot="dialog-overlay"]'))), false,
        'Toast must stay outside the modal overlay');
      assert.equal(await toast.evaluate(node => Boolean(node.closest('[inert], [aria-hidden="true"]'))), false,
        'Modal must not disable the toast');
      const close = toast.getByRole('button', { name: 'Close toast', exact: true });
      await close.focus();
      assert.equal(await close.evaluate(node => node === document.activeElement), true, 'Toast must accept keyboard focus');
      if (viewport.width > 760) {
        await page.locator('.account-settings-dialog > [data-slot="dialog"] > [data-slot="dialog-close"]').click();
        await page.waitForURL(`${root}/`, { waitUntil: 'domcontentloaded' });
        await toast.waitFor();
        await page.getByRole('link', { name: 'Alert settings', exact: true }).click();
        await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      }
      await close.click();
      await toast.waitFor({ state: 'detached' });
      assert.equal(await page.locator('.account-settings-dialog').isVisible(), true, 'Dismissal must keep settings open');
      assert.equal(await page.locator('#bulletin-view').getAttribute('aria-hidden'), 'true');
      await page.close();
      console.log(`PASS modal toast outside overlay, focus, dismissal, and background isolation: ${viewport.width}`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
