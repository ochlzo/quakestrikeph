// Requires Playwright and a running Bulletin server; BULLETIN_URL overrides localhost:4321.
const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { chromium } = require("playwright");

(async () => {
  const { locationLabel } = await import("../src/lib/events.ts");
  const descriptions = [
    "011 km N 78° W of Balut Island (Municipality of Sarangani) (Davao Occidental)",
    "009 km N 01° E of Socorro (Surigao Del Norte)",
    "016 km N 62° W of Monreal (Masbate)",
    "10 km S of Legazpi City (Albay)",
    "Offshore east of Mindanao",
    "Location unavailable",
  ];
  const labels = [
    "11 km N 78° W of Balut Island (Municipality of Sarangani) (Davao Occidental)",
    "9 km N 01° E of Socorro (Surigao Del Norte)",
    "16 km N 62° W of Monreal (Masbate)",
    ...descriptions.slice(3),
  ];
  assert.deepEqual(descriptions.map(locationLabel), labels);
  assert.equal(locationLabel(""), "");
  assert.equal(locationLabel("000 km S of Glan"), "0 km S of Glan");
  assert.equal(locationLabel("000.5 km S of Glan"), "0.5 km S of Glan");
  assert.equal(locationLabel("001.50 km N 01° E of Glan"), "1.50 km N 01° E of Glan");
  assert.equal(locationLabel("010 metres S of Glan"), "010 metres S of Glan");
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const events = descriptions.map((locationDescription, index) => ({
      eventId: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      eventTime: "2026-09-30T04:00:00Z", magnitude: 2.6,
      latitude: 13, longitude: 123, depthKm: index === 0 ? null : 10,
      locationDescription, forecast: null,
    }));
    await page.route("**/api/v1/earthquakes/search", (route) => route.fulfill({ json: {
      items: events, hasMore: false, nextCursor: null, fetchedAt: "2026-09-30T04:00:00Z",
    } }));
    await page.route("**/api/v1/earthquakes/00000000-*", (route) => route.fulfill({ json: {
      item: { ...events[0], eventRevisionId: events[0].eventId, origin: null,
        source: { provider: "PHIVOLCS", url: "https://www.phivolcs.dost.gov.ph/" } },
    } }));
    await mkdir(".astro", { recursive: true });
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(process.env.BULLETIN_URL || "http://localhost:4321");
      if (width <= 760) await page.getByRole("button", { name: "Show earthquakes" }).click();
      const rows = page.locator(".event-row-v2:not(.event-row-skeleton)");
      await rows.first().waitFor();
      assert.deepEqual(await rows.locator("b").allTextContents(), labels);
      assert.equal(await rows.first().locator(".row-v2-measure small").textContent(), "Unknown depth");
      const depthBounds = await rows.first().locator(".row-v2-measure small").boundingBox();
      const locationBounds = await rows.first().locator(".row-v2-detail").boundingBox();
      assert(depthBounds.x + depthBounds.width <= locationBounds.x, "Depth must stay in its own column");
      assert(await rows.first().locator("time").evaluate((element) => parseFloat(getComputedStyle(element).fontSize)) >= 12);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({ path: `.astro/readability-${width}.png`, fullPage: true });
      await rows.first().click();
      assert.equal(await page.locator(".selected-card h2").textContent(), labels[0]);
      assert.equal(await page.locator(".source-location").count(), 0);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({ path: `.astro/readability-selected-${width}.png`, fullPage: true });
    }
    assert.deepEqual(errors, []);
    console.log("PASS source location headings, kilometre formatting, metadata size and narrow layouts");
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
