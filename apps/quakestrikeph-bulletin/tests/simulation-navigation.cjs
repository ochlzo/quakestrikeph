const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const base = new URL(process.env.BULLETIN_URL || 'http://localhost:4321');
const home = new URL('/', base);
const simulation = new URL('/simulate-forecast', base);

const tab = (page, name) => page.getByRole('tab', { name, exact: true });
const sidebar = (page) => page.getByRole('navigation', { name: 'Main navigation' });
const waitForBulletin = (page) => page.locator('#bulletin-view > astro-island[ssr]').waitFor({ state: 'detached' });
const waitForSimulationHeader = (page) => page.locator('astro-island[component-export="SimulationHeader"][ssr]').waitFor({ state: 'detached' });

async function mobileHeaderBounds(page) {
  const header = page.locator('header.bulletin-header');
  const title = header.getByRole('link', { name: 'QuakeStrike PH Bulletin home' });
  assert.equal(await title.textContent(), 'QuakeStrike PH');
  return Promise.all([
    header.boundingBox(),
    header.getByRole('button', { name: 'Toggle sidebar' }).boundingBox(),
    title.boundingBox(),
    header.getByRole('link', { name: 'Receive alerts' }).boundingBox(),
  ]);
}

async function watchTabMotion(page) {
  await page.addInitScript(() => {
    window.tabSlides = [];
    const animate = Element.prototype.animate;
    Element.prototype.animate = function (frames, options) {
      if (this.matches('.bulletin-nav-indicator') && frames.translate) {
        window.tabSlides.push({ distance: parseFloat(frames.translate[0]), duration: options.duration });
      }
      return animate.call(this, frames, options);
    };
  });
}

(async () => {
  const browser = await chromium.launch();
  try {
    const desktop = await browser.newPage({ viewport: { width: 1575, height: 883 } });
    await desktop.route((url) => url.origin !== base.origin, (route) => route.abort());
    await watchTabMotion(desktop);
    await desktop.goto(home.href, { waitUntil: 'domcontentloaded' });
    await waitForBulletin(desktop);
    assert.deepEqual(await desktop.getByRole('tablist', { name: 'Main navigation' }).getByRole('tab').allTextContents(),
      ['Earthquakes', 'Simulate Forecast', 'About']);
    assert.equal(await tab(desktop, 'Earthquakes').getAttribute('aria-selected'), 'true');

    await tab(desktop, 'Earthquakes').press('ArrowRight');
    await desktop.waitForFunction(() => document.activeElement?.getAttribute('data-key') === '/simulate-forecast');
    await desktop.keyboard.press('Enter');
    await desktop.waitForURL(simulation.href);
    await desktop.waitForFunction(() => window.tabSlides.length === 1);
    assert.equal(await tab(desktop, 'Simulate Forecast').getAttribute('aria-selected'), 'true');
    const header = desktop.locator('header.simulation-header');
    const logo = await header.getByRole('link', { name: 'QuakeStrike PH Bulletin home' }).boundingBox();
    const tabs = await header.getByRole('tablist').boundingBox();
    const alerts = await header.getByRole('link', { name: 'Receive alerts' }).boundingBox();
    assert.ok(logo.x + logo.width < tabs.x && tabs.x + tabs.width < alerts.x);

    await tab(desktop, 'Earthquakes').click();
    await desktop.waitForURL(home.href);
    await desktop.waitForFunction(() => window.tabSlides.length === 2);
    const slides = await desktop.evaluate(() => window.tabSlides);
    assert.ok(slides[0].distance < 0 && slides[1].distance > 0);
    assert.deepEqual(slides.map(({ duration }) => duration), [320, 320]);

    await desktop.emulateMedia({ reducedMotion: 'reduce' });
    await tab(desktop, 'Simulate Forecast').click();
    await desktop.waitForURL(simulation.href);
    assert.equal(await tab(desktop, 'Simulate Forecast').getAttribute('aria-selected'), 'true');
    assert.equal(await desktop.evaluate(() => window.tabSlides.length), 2);

    const mobile = await browser.newPage({ viewport: { width: 384, height: 824 }, isMobile: true, hasTouch: true });
    await mobile.route((url) => url.origin !== base.origin, (route) => route.abort());
    await mobile.goto(home.href, { waitUntil: 'domcontentloaded' });
    await waitForBulletin(mobile);
    await mobile.evaluate(() => document.fonts.ready);
    const homeHeader = await mobileHeaderBounds(mobile);
    await mobile.getByRole('button', { name: 'Toggle sidebar' }).click();
    await sidebar(mobile).getByRole('link', { name: 'Simulate Forecast' }).click();
    await mobile.waitForURL(simulation.href);
    await waitForSimulationHeader(mobile);
    await mobile.evaluate(() => document.fonts.ready);
    assert.deepEqual(await mobileHeaderBounds(mobile), homeHeader);
    await mobile.locator('.simulate-source:visible').getByText('The model needs seven days', { exact: false }).waitFor();
    await mobile.getByRole('button', { name: 'Toggle sidebar' }).click();
    const current = sidebar(mobile).getByRole('link', { name: 'Simulate Forecast' });
    await current.waitFor();
    assert.equal(await current.getAttribute('aria-current'), 'page');
    await sidebar(mobile).getByRole('link', { name: 'Earthquakes' }).click();
    await mobile.waitForURL(home.href);
    console.log('Simulation navigation works on desktop and mobile and respects reduced motion.');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
