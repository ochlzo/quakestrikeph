// Run with the dev server running: node tests/magnitude-filter.cjs (requires Playwright).
const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const requests = [];
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const fixtures = [2.9, 3, 3.9, 4, 4.9, 5, 5.9, 6, 7].map((magnitude, index) => ({
      eventId: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      eventTime: "2026-09-30T04:00:00Z",
      magnitude,
      latitude: 13 + index / 10,
      longitude: 123,
      depthKm: 10,
      locationDescription: `Sample location ${index}`,
      forecast: null,
    }));
    await page.route("**/api/v1/earthquakes/search", async (route) => {
      const body = route.request().postDataJSON();
      requests.push(body);
      const matching = fixtures.filter((event) => !body.magnitudeRanges ||
        body.magnitudeRanges.some((range) =>
          (range.from === undefined || event.magnitude >= range.from) &&
          (range.below === undefined || event.magnitude < range.below),
        ),
      );
      const start = body.cursor ? Number(body.cursor) : 0;
      const nextCursor = start + 2 < matching.length ? String(start + 2) : null;
      await route.fulfill({ json: {
        items: matching.slice(start, start + 2),
        hasMore: nextCursor !== null,
        nextCursor,
        fetchedAt: "2026-09-30T04:00:00Z",
      } });
    });
    await page.goto(process.env.BULLETIN_URL || "http://localhost:4321");
    const input = page.getByRole("combobox", { name: "Magnitude ranges", exact: true });
    const chips = page.locator('[data-slot="combobox-chip"]');
    const chevron = page.locator('.magnitude-filter-trigger > svg');
    const rows = page.locator(".event-row-v2:not(.event-row-skeleton)");
    await rows.first().waitFor();
    const initialCount = requests.length;
    assert.equal(await chips.count(), 0);
    assert.equal(await input.getAttribute("placeholder"), "All magnitudes");
    assert.equal(await chevron.evaluate((element) => getComputedStyle(element).transform), "none");
    assert.equal(await page.locator('[aria-label="Clear magnitude selections"]').count(), 0);
    const stone = page.locator(".magnitude-filter-icon");
    assert.equal(await stone.getAttribute("aria-hidden"), "true");
    assert.equal(await stone.evaluate((element) => getComputedStyle(element).color),
      await page.locator(".date-filter-trigger .filter-select-icon").evaluate(
        (element) => getComputedStyle(element).color));
    await page.locator(".date-filter-trigger").click();
    const dateOption = page.locator('.date-filter-popover [data-slot="select-item"]').first();
    await dateOption.hover();
    const dateHoverColor = await dateOption.evaluate((element) => getComputedStyle(element).backgroundColor);
    assert.equal(dateHoverColor, "rgb(233, 247, 247)");
    await page.keyboard.press("Escape");
    await page.locator(".date-filter-popover").waitFor({ state: "hidden" });

    await input.click();
    const magnitudeOption = page.getByRole("option").first();
    await magnitudeOption.hover();
    assert.equal(await magnitudeOption.evaluate((element) => getComputedStyle(element).backgroundColor), dateHoverColor);
    assert.equal(await input.getAttribute("placeholder"), "Search ranges");
    await page.waitForTimeout(200);
    assert.equal(await chevron.evaluate((element) => getComputedStyle(element).transform), "matrix(-1, 0, 0, -1, 0, 0)");
    assert.equal(await page.getByRole("option").count(), 6);
    assert.equal(await page.getByRole("option").first().textContent(), "All magnitudes");
    assert.equal(await page.getByRole("option").first().getAttribute("aria-selected"), "true");
    await page.getByRole("option", { name: "All magnitudes", exact: true }).click();
    assert.equal(await chips.count(), 0);
    assert.equal(await input.getAttribute("placeholder"), "Search ranges");
    await input.fill("5.0");
    assert.deepEqual(await page.getByRole("option").allTextContents(), [
      "M5.0 - M5.9",
    ]);
    await input.fill("nothing matches");
    await page.getByText("No matching ranges.").waitFor();
    await input.fill("");
    await page.getByRole("option", { name: "Below M3.0", exact: true }).click();
    await page.getByRole("option", { name: "M5.0 - M5.9", exact: true }).click();
    await page.getByRole("option", { name: "Above M6.0", exact: true }).click();
    assert.equal(await chips.count(), 3);
    assert.equal(await chips.filter({ hasText: "All magnitudes" }).count(), 0);
    await page.waitForTimeout(350);
    assert.equal(requests.length, initialCount, "Draft selections must not search yet");

    // Each dot shares its map legend color, including the selected chips.
    for (const className of ["mag-under-3", "mag-5", "mag-6"]) {
      const color = await page.locator(`.map-legend .${className}`).evaluate(
        (element) => getComputedStyle(element).backgroundColor,
      );
      assert.equal(await page.locator(`.magnitude-filter .${className}`).evaluate(
        (element) => getComputedStyle(element).backgroundColor,
      ), color);
    }
    await mkdir(".astro/magnitude-verification", { recursive: true });
    await page.screenshot({ path: ".astro/magnitude-verification/desktop.png" });

    await page.locator("#events-title").click();
    await page.waitForTimeout(200);
    assert.equal(await chevron.evaluate((element) => getComputedStyle(element).transform), "none");
    await page.waitForFunction(() => document.querySelectorAll(".event-row-skeleton").length === 0);
    assert.deepEqual(requests.at(-1).magnitudeRanges, [
      { from: 6 }, { from: 5, below: 6 }, { below: 3 },
    ]);
    assert.equal(await rows.count(), 2);
    await page.getByRole("link", { name: "Load more earthquakes", exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll(".event-row-v2").length === 4);
    assert.deepEqual(requests.at(-1).magnitudeRanges, requests.at(-2).magnitudeRanges);
    assert.equal(requests.at(-1).cursor, "2");

    await input.click();
    const beforeRemove = requests.length;
    await chips.filter({ hasText: "Above M6.0" }).locator('[data-slot="combobox-chip-remove"]').click();
    assert.equal(await chips.count(), 2);
    await page.waitForTimeout(350);
    assert.equal(requests.length, beforeRemove, "Chip removal must remain a draft");
    await input.press("Escape");
    await input.focus();
    await input.press("Tab"); // The library skips the dropdown trigger in tab order.
    await page.waitForFunction(() => document.querySelectorAll(".event-row-skeleton").length === 0);
    assert.deepEqual(requests.at(-1).magnitudeRanges, [{ from: 5, below: 6 }, { below: 3 }]);

    await input.click();
    const beforeAll = requests.length;
    await page.getByRole("option", { name: "All magnitudes", exact: true }).click();
    assert.equal(await chips.count(), 0);
    assert.equal(await input.getAttribute("placeholder"), "Search ranges");
    assert.equal(await page.getByRole("option", { selected: true }).count(), 1);
    await page.waitForTimeout(350);
    assert.equal(requests.length, beforeAll, "All magnitudes must remain a draft until blur");
    await page.locator("#events-title").click();
    await page.waitForFunction(() => document.querySelectorAll(".event-row-skeleton").length === 0);
    assert.equal(requests.at(-1).magnitudeRanges, undefined);
    assert.equal(await input.getAttribute("placeholder"), "All magnitudes");

    await page.setViewportSize({ width: 390, height: 844 });
    await input.click();
    for (const name of ["Below M3.0", "M3.0 - M3.9", "M4.0 - M4.9", "M5.0 - M5.9", "Above M6.0"]) {
      await page.getByRole("option", { name, exact: true }).click();
    }
    assert.equal(await chips.count(), 5);
    const fieldBounds = await page.locator(".magnitude-filter-field").boundingBox();
    const chevronBounds = await chevron.boundingBox();
    assert.ok(fieldBounds.x + fieldBounds.width - chevronBounds.x - chevronBounds.width <= 20,
      "Chevron stays at the right edge when chips wrap");
    await page.screenshot({ path: ".astro/magnitude-verification/mobile.png" });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.getByRole("option", { name: "All magnitudes", exact: true }).click();
    await input.fill("Above M6.0");
    await input.press("ArrowDown");
    await input.press("Enter");
    assert.equal(await chips.count(), 1);
    await input.press("Backspace");
    assert.equal(await chips.count(), 0);
    assert.equal(await input.getAttribute("placeholder"), "Search ranges");
    await page.locator("#events-title").click();
    assert.equal(await input.getAttribute("placeholder"), "All magnitudes");
    assert.deepEqual(errors, []);
    console.log("PASS: plain default text, focus placeholder and chevron rotation, exclusive All magnitudes, searchable bands, deferred apply, pagination, chip removal, keyboard, and mobile layout");
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
