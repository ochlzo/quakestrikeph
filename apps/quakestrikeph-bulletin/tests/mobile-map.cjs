// Run against a built or dev server: BULLETIN_URL=http://localhost:4321 node tests/mobile-map.cjs
const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "warn" && message.text().includes("Supplemental map labels unavailable")) {
        errors.push(message.text());
      }
    });
    let landmarkRequests = 0;
    page.on("request", (request) => {
      if (request.url().endsWith("/assets/map/philippines-landmarks.geojson")) landmarkRequests++;
    });
    const landmarkResponse = page.waitForResponse((response) => response.url().endsWith("/assets/map/philippines-landmarks.geojson"));
    const events = Array.from({ length: 12 }, (_, index) => ({
      eventId: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      eventTime: "2026-09-30T04:00:00Z", magnitude: 2.6,
      latitude: 13 + index / 10, longitude: 123, depthKm: 10,
      locationDescription: `Observed earthquake in Albay ${index}`, forecast: null,
    }));
    await page.route("**/api/v1/earthquakes/search", (route) => route.fulfill({ json: {
      items: events, hasMore: false, nextCursor: null, fetchedAt: "2026-09-30T04:00:00Z",
    } }));
    await page.route("**/api/v1/earthquakes/00000000-*", (route) => route.fulfill({ json: {
      item: { ...events.find((event) => route.request().url().endsWith(event.eventId)),
        eventRevisionId: events[0].eventId, origin: null,
        source: { provider: "PHIVOLCS", url: "https://www.phivolcs.dost.gov.ph/" }, forecast: {
          forecastId: events[0].eventId, modelReleaseId: events[0].eventId,
          windowStart: "2026-09-30T04:00:00Z", windowEnd: "2026-10-01T04:00:00Z",
          expired: false, probabilityM1Plus24h: 0.99, probabilityM4Plus24h: 0.1,
          probabilityM5Plus24h: 0.01, expectedM1PlusCount24h: 2,
          activityRadiusMedianKm24h: 93, maximumMagnitudeQ05_24h: 1,
          maximumMagnitudeQ50_24h: 2, maximumMagnitudeQ95_24h: 4,
        } },
    } }));
    await page.goto(process.env.BULLETIN_URL || "http://localhost:4321");
    const rows = page.locator(".event-row-v2:not(.event-row-skeleton)");
    await page.getByRole("button", { name: "Show earthquakes" }).waitFor();
    assert.equal(await page.getByRole("region", { name: "Magnitude legend" }).isVisible(), true, "Mobile legend starts open");
    await page.waitForFunction(() => !document.querySelector('.terrain-button').disabled);
    const labels = await (await landmarkResponse).json();
    assert.equal(labels.features.length, 2264);
    assert(labels.features.every((feature) => feature.properties.category === "landmarks"));
    assert.equal(await page.locator(".map-plate").count(), 0, "Loaded map hides the relief placeholder");
    const attribution = page.locator(".maplibregl-ctrl-attrib");
    assert.equal(await attribution.evaluate((el) => el.classList.contains("maplibregl-compact")), false, "Mobile attribution stays expanded");
    assert.equal(await attribution.evaluate((el) => getComputedStyle(el).fontSize), "8px");
    assert.equal(await attribution.locator(".maplibregl-ctrl-attrib-inner").isVisible(), true);
    await page.getByRole("button", { name: "Show the Philippines" }).click();
    assert.equal(await attribution.locator(".maplibregl-ctrl-attrib-inner").isVisible(), true);
    assert.equal(await page.locator(".maplibregl-ctrl-scale").evaluate((el) => el.clientWidth <= 96), true);
    assert.equal(await page.getByRole("link", { name: "Search", exact: true }).count(), 0);
    assert.equal(await page.getByRole("tab", { name: "Earthquakes", exact: true }).count(), 1);
    await mkdir(".astro", { recursive: true });
    const map = page.locator(".map-panel");
    const list = page.locator(".event-list");
    for (const width of [320, 390, 609]) {
      await page.setViewportSize({ width, height: 844 });
      assert.equal(await map.isVisible(), true);
      assert.equal(await page.locator(".map-disclosure").count(), 0);
      const legend = page.getByRole("region", { name: "Magnitude legend" });
      const toggle = page.getByRole("button", { name: "Magnitude legend" });
      assert.equal(await legend.isVisible(), false);
      const icon = await toggle.boundingBox();
      assert.equal(icon.width, 24);
      assert.equal(icon.height, 24);
      await toggle.click();
      assert.equal(await legend.isVisible(), true);
      const panel = await map.boundingBox();
      const popup = await legend.boundingBox();
      assert(popup.x >= panel.x && popup.y >= panel.y && popup.x + popup.width <= panel.x + panel.width, "Legend stays inside the map");
      assert.equal(await legend.locator("span").count(), 5);
      await toggle.click();
      assert.equal(await legend.isVisible(), false);
      await toggle.focus();
      await page.keyboard.press("Enter");
      assert.equal(await legend.isVisible(), true);
      await page.keyboard.press("Escape");
      assert.equal(await legend.isVisible(), false);
      await toggle.click();
      await page.getByRole("button", { name: "Zoom in", exact: true }).click();
      assert.equal(await legend.isVisible(), false);
      await toggle.click();
      const canvas = await page.locator(".map-canvas").boundingBox();
      await page.mouse.move(canvas.x + 60, canvas.y + 100);
      await page.mouse.down();
      await page.mouse.move(canvas.x + 110, canvas.y + 130, { steps: 4 });
      await page.mouse.up();
      assert.equal(await legend.isVisible(), false, "Dragging the map dismisses the legend");
      for (const control of await page.locator(".terrain-button, .map-tools button").all()) {
        const box = await control.boundingBox();
        assert(box.width >= 32 && box.height === 32, "Mobile controls have compact surfaces");
        assert.equal(await control.evaluate((el) => getComputedStyle(el, "::before").top), "-6px", "Extended touch target");
      }
      const terrain = await page.locator(".terrain-button").boundingBox();
      const tools = await page.locator(".map-tools").boundingBox();
      assert(terrain.x + terrain.width <= tools.x, "Map controls must not overlap");
      assert.equal(await page.locator(".filter-bar").count(), 0, "Filters live in the closed drawer");
      const mapBounds = await map.boundingBox();
      assert.equal(Math.round(mapBounds.height), 739, "Map fills the viewport below the header");
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "No horizontal overflow");
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: ".astro/mobile-list.png", fullPage: true });
    await page.waitForFunction(() => !document.querySelector('.terrain-button').disabled);
    await page.waitForFunction(() => {
      const canvas = document.querySelector(".map-canvas canvas");
      return canvas && canvas.clientHeight === document.querySelector(".map-panel").clientHeight;
    });
    const trigger = page.getByRole("button", { name: "Show earthquakes" });
    await trigger.click();
    const drawer = page.getByRole("dialog", { name: "Earthquake search and results" });
    await drawer.waitFor();
    await rows.first().waitFor();
    const top = await drawer.boundingBox();
    assert(Math.abs(top.y - 844 * 0.35) < 3, "Drawer opens at 65% of viewport height");
    assert.equal(await drawer.locator(".events-head").isVisible(), false);
    const searchBox = await drawer.locator(".search-field").boundingBox();
    const dateBox = await drawer.locator(".date-filter-trigger").boundingBox();
    const magnitudeBox = await drawer.locator(".magnitude-filter-field").boundingBox();
    assert(searchBox.y < dateBox.y && Math.abs(dateBox.y - magnitudeBox.y) < 1);
    assert(dateBox.x + dateBox.width <= magnitudeBox.x);
    const scroll = drawer.locator(".earthquake-drawer-scroll");
    assert.equal(await scroll.evaluate((el) => getComputedStyle(el).scrollbarWidth), "none");
    await scroll.evaluate((el) => { el.scrollTop = el.scrollHeight; });
    assert(await scroll.evaluate((el) => el.scrollTop > 0), "Drawer contents scroll independently");
    assert.equal(await page.evaluate(() => scrollY), 0);
    await scroll.evaluate((el) => { el.scrollTop = 0; });
    await drawer.getByRole("button", { name: "Expand earthquake drawer" }).click();
    await page.waitForFunction(() => document.querySelector('[data-slot="drawer-popup"]').hasAttribute('data-expanded'));
    assert((await drawer.boundingBox()).y <= 1, "Full-height snap is available");
    await drawer.getByRole("button", { name: "Collapse earthquake drawer" }).click();
    const handle = await drawer.locator('[data-slot="drawer-swipe-handle"]').boundingBox();
    await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
    await page.mouse.down();
    await page.mouse.move(handle.x + handle.width / 2, 10, { steps: 15 });
    await page.mouse.up();
    await page.waitForFunction(() => document.querySelector('[data-slot="drawer-popup"]').hasAttribute('data-expanded'));
    await drawer.getByRole("button", { name: "Collapse earthquake drawer" }).click();

    await drawer.locator(".date-filter-trigger").click();
    await page.getByRole("option", { name: "Last 7 days", exact: true }).click();
    assert(await drawer.isVisible(), "Date popover does not dismiss drawer");
    await drawer.locator(".magnitude-filter-field input").click();
    await page.getByRole("option", { name: "Below M3.0", exact: true }).click();
    assert(await drawer.isVisible(), "Magnitude popover does not dismiss drawer");
    await drawer.locator(".search-field input").click();
    await rows.first().click();
    await drawer.locator(".date-filter-trigger").click();
    await page.getByRole("option").last().click();
    const calendar = page.getByRole("dialog", { name: "Choose custom date range" });
    await calendar.waitFor();
    await page.keyboard.press("Escape");
    await calendar.waitFor({ state: "hidden" });
    assert(await drawer.isVisible(), "Closing custom calendar keeps drawer open");
    await page.screenshot({ path: ".astro/mobile-drawer-open.png" });
    await page.getByRole("button", { name: "Close earthquakes" }).click();
    await drawer.waitFor({ state: "hidden" });
    await page.getByRole("heading", { name: "Forecast Overview" }).waitFor();
    await page.locator(".maplibregl-canvas").click({ position: { x: 20, y: 140 } });
    assert(await page.getByRole("heading", { name: "Forecast Overview" }).isVisible(), "Clicking the map keeps the forecast open");
    await page.screenshot({ path: ".astro/mobile-map-open.png" });
    await page.getByRole("button", { name: "Close forecast overview" }).click();
    await page.locator(".forecast-map-annotation").waitFor({ state: "hidden" });
    assert(await page.locator(".quake-marker.is-selected").evaluate((el) => el === document.activeElement), "Closing the overview returns focus to the selected marker");
    await page.keyboard.press("Enter");
    await page.getByRole("heading", { name: "Forecast Overview" }).waitFor();
    const terrainToggle = page.getByRole("button", { name: "3D terrain", exact: true });
    await terrainToggle.click();
    assert.equal(await terrainToggle.getAttribute("aria-pressed"), "true");
    for (let step = 0; step < 7; step++) {
      await page.locator(".maplibregl-canvas").press("Shift+ArrowUp");
      // Each keyboard camera animation lasts 300 ms; let it settle before the next step.
      await page.waitForTimeout(350);
    }
    await page.getByRole("button", { name: "Zoom in", exact: true }).click();
    await page.waitForTimeout(400);
    assert(await page.getByRole("heading", { name: "Forecast Overview" }).isVisible(), "3D tilt and zoom preserve the selected forecast");
    await page.screenshot({ path: ".astro/mobile-map-3d.png" });
    await terrainToggle.click();
    assert.equal(await terrainToggle.getAttribute("aria-pressed"), "false");
    await trigger.click();
    await drawer.waitFor();
    assert(Math.abs((await drawer.boundingBox()).y - 844 * 0.35) < 3, "Reopens at compact snap");
    assert.equal(await drawer.locator('.date-filter-trigger').innerText(), "Last 7 days", "Filters persist between openings");
    await page.mouse.click(180, 150);
    await drawer.waitFor({ state: "hidden" });
    await trigger.click();
    await drawer.waitFor();

    await page.keyboard.press("Escape");
    await drawer.waitFor({ state: "hidden" });
    assert.equal(await trigger.evaluate((el) => el === document.activeElement), true, "Focus returns to trigger");

    for (const viewport of [{ width: 320, height: 640 }, { width: 609, height: 844 }, { width: 700, height: 390 }]) {
      await page.setViewportSize(viewport);
      await trigger.click();
      await drawer.waitFor();
      const bounds = await drawer.boundingBox();
      assert(Math.abs(bounds.y - viewport.height * 0.35) < 3);
      assert.equal(bounds.width, viewport.width);
      assert(await scroll.evaluate((el) => el.clientHeight > 0 && el.scrollHeight > el.clientHeight));
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.getByRole("button", { name: "Close earthquakes" }).click();
      await drawer.waitFor({ state: "hidden" });
    }
    await trigger.click();
    await drawer.waitFor();
    await page.setViewportSize({ width: 1440, height: 900 });
    await drawer.waitFor({ state: "hidden" });
    assert(await map.isVisible(), "Desktop map stays visible");
    assert.equal(await page.getByRole("tab", { name: "Earthquakes", exact: true }).count(), 1);
    assert.equal(await page.getByRole("link", { name: "Search", exact: true }).count(), 0);
    assert.equal(await page.getByRole("link", { name: "Map", exact: true }).count(), 0);
    assert.equal((await page.getByRole("button", { name: "Zoom in" }).boundingBox()).height, 32);
    assert.equal(await page.locator(".terrain-button").evaluate((el) => getComputedStyle(el).fontSize), "14px");

    assert.equal(await page.locator(".map-disclosure").count(), 0);
    assert.equal(await list.evaluate((element) => getComputedStyle(element).overflowY), "auto");
    assert(await page.getByRole("region", { name: "Magnitude legend" }).isVisible());
    assert.equal(await page.getByRole("button", { name: "Magnitude legend" }).isVisible(), false);
    await page.screenshot({ path: ".astro/mobile-map-desktop.png" });
    // Check the same high-tilt sky at desktop size without the forecast annotation covering it.
    const desktopCanvas = page.locator(".maplibregl-canvas");
    await desktopCanvas.click({ position: { x: 40, y: 140 } });
    assert(await page.getByRole("heading", { name: "Forecast Overview" }).isVisible(), "Clicking away keeps the desktop forecast open");
    await page.getByRole("button", { name: "Close forecast overview" }).click();
    await page.locator(".forecast-map-annotation").waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "Show the Philippines", exact: true }).click();
    await page.waitForTimeout(750);
    await terrainToggle.click();
    await page.waitForTimeout(550);
    for (let step = 0; step < 5; step++) {
      await desktopCanvas.press("Shift+ArrowUp");
      await page.waitForTimeout(350);
    }
    assert.equal(await page.locator(".map-plate").count(), 0);
    await page.screenshot({ path: ".astro/map-native-sky-desktop.png" });
    assert.equal(landmarkRequests, 1, "Mode and camera changes reuse the landmark asset");
    const desktopLandmarks = page.waitForResponse((response) => response.url().endsWith("/assets/map/philippines-landmarks.geojson"));
    await page.reload();
    await desktopLandmarks;
    await page.waitForFunction(() => !document.querySelector('.terrain-button').disabled);
    assert.equal(await attribution.evaluate((el) => el.classList.contains("maplibregl-compact")), false, "Desktop attribution stays expanded");
    assert.equal(await attribution.evaluate((el) => getComputedStyle(el).fontSize), "12px");
    assert.equal(await attribution.locator(".maplibregl-ctrl-attrib-inner").isVisible(), true);
    assert.deepEqual(errors, []);
    console.log("PASS mobile fullscreen map, snap drawer, scrolling, filters, dismissal and desktop layout");
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
