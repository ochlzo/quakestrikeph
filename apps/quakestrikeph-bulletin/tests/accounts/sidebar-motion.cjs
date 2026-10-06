const assert = require('node:assert/strict');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'no-preference' });
    await page.route('**/api/v1/account**', route => route.fulfill({ json: {
      account: { userId: 'fixture-user', displayName: 'Maria', email: 'maria@example.invalid', phone: null, onboardingCompleted: true, status: 'active', emailEnabled: false, smsEnabled: false, magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null },
      pending: null, nextStep: 'complete', deliveryAvailable: false,
    } }));
    await page.goto('http://127.0.0.1:4332/alerts?signed=1');
    await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
    const sampling = page.evaluate(async () => {
      const samples = [];
      const until = performance.now() + 500;
      while (performance.now() < until) {
        const state = document.querySelector('[data-slot="sidebar"][data-state]').dataset.state;
        if (state === 'expanded') samples.push(...[...document.querySelectorAll('.bulletin-mobile-nav a span')].map(el => el.getBoundingClientRect().height));
        await new Promise(requestAnimationFrame);
      }
      return samples;
    });
    await page.locator('[data-slot="sidebar-container"]').hover();
    const samples = await sampling;
    console.log('Navigation label height during expansion:', Math.min(...samples), 'to', Math.max(...samples));
    assert.ok(samples.length > 0);
    assert.ok(Math.max(...samples) <= 24, 'Navigation labels must stay on one line throughout expansion');
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
