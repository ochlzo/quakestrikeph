// Run with the dev server running: node tests/magnitude-filter.cjs (requires Playwright).
const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const requests = [];
    let holdNextResponse = false;
    let releaseResponse;
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
      if (holdNextResponse) {
        holdNextResponse = false;
        await new Promise((resolve) => { releaseResponse = resolve; });
      }
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
    await page.locator('astro-island[ssr]').waitFor({ state: "detached" });
    const input = page.getByRole("combobox", { name: "Magnitude ranges", exact: true });
    const chips = page.locator('[data-slot="combobox-chip"]');
    const chevron = page.locator('.magnitude-filter-trigger > svg');
    const rows = page.locator(".event-row-v2:not(.event-row-skeleton)");
    await rows.filter({ hasText: "Sample location 0" }).first().waitFor();
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
    const accentColor = await page.evaluate(() => {
      const probe = document.createElement("span");
      probe.style.backgroundColor = "var(--accent)";
      document.body.append(probe);
      const color = getComputedStyle(probe).backgroundColor;
      probe.remove();
      return color;
    });
    assert.equal(dateHoverColor, accentColor, "Date options use the central accent token");
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
    await page.clock.install();
    await page.clock.pauseAt(new Date(Date.now() + 1000));
    holdNextResponse = true;
    await page.getByRole("option", { name: "Below M3.0", exact: true }).click();
    await page.clock.runFor(150);
    await page.getByRole("option", { name: "M5.0 - M5.9", exact: true }).click();
    await page.clock.runFor(150);
    await page.getByRole("option", { name: "Above M6.0", exact: true }).click();
    assert.equal(await chips.count(), 3);
    assert.equal(await chips.filter({ hasText: "All magnitudes" }).count(), 0);
    await page.clock.runFor(299);
    assert.equal(requests.length, initialCount, "Each selection resets the 300 ms debounce");
    await page.clock.runFor(1);
    await page.clock.resume();
    await page.waitForTimeout(100);
    assert.equal(requests.length, initialCount + 1, "One request applies the final selection without blur");
    assert.ok(await page.locator('.magnitude-filter-popover').isVisible());
    assert.equal(await rows.count(), 0, "Hide previous results during refresh");
    assert.equal(await page.locator(".event-row-skeleton").count(), 6);
    assert.equal(await page.locator(".events-head p").textContent(), "Browse observed events across the Philippines.");
    assert.equal(await page.getByText("Updating earthquakes…", { exact: true }).count(), 0);
    assert.equal(await page.locator(".event-list-skeleton").getAttribute("aria-busy"), "true");
    releaseResponse();
    await page.waitForFunction(() => document.querySelector('#event-list')?.getAttribute('aria-busy') === 'false');

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
    assert.equal(requests.length, initialCount + 1, "Blur must not trigger another request");
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
    assert.equal(requests.length, beforeRemove + 1, "Chip removal applies without blur");
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
    assert.equal(requests.length, beforeAll + 1, "All magnitudes applies without blur");
    await page.locator("#events-title").click();
    await page.waitForFunction(() => document.querySelectorAll(".event-row-skeleton").length === 0);
    assert.equal(requests.at(-1).magnitudeRanges, undefined);
    assert.equal(await input.getAttribute("placeholder"), "All magnitudes");

    // A slow response for an earlier selection must not replace newer results.
    await input.click();
    holdNextResponse = true;
    const beforeSlow = requests.length;
    await page.getByRole("option", { name: "M4.0 - M4.9", exact: true }).click();
    await page.waitForTimeout(350);
    assert.equal(requests.length, beforeSlow + 1);
    const releaseSlowResponse = releaseResponse;
    await page.getByRole("option", { name: "All magnitudes", exact: true }).click();
    await page.getByRole("option", { name: "Above M6.0", exact: true }).click();
    await page.waitForTimeout(350);
    assert.equal(requests.length, beforeSlow + 2);
    await page.waitForFunction(() => document.querySelector('#event-list')?.getAttribute('aria-busy') === 'false');
    assert.deepEqual(await rows.locator('.row-v2-measure strong').allTextContents(), ['M6.0', 'M7.0']);
    releaseSlowResponse();
    await page.waitForTimeout(150);
    assert.deepEqual(await rows.locator('.row-v2-measure strong').allTextContents(), ['M6.0', 'M7.0'],
      "A stale response must not overwrite the latest magnitude results");
    await page.getByRole("option", { name: "All magnitudes", exact: true }).click();
    await page.waitForTimeout(350);
    await page.locator("#events-title").click();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: "Show earthquakes" }).click();
    await page.getByRole("dialog", { name: "Earthquake search and results" }).waitFor();
    await input.click();
    for (const name of ["Below M3.0", "M3.0 - M3.9", "M4.0 - M4.9", "M5.0 - M5.9", "Above M6.0"]) {
      await page.getByRole("option", { name, exact: true }).click();
      await page.waitForFunction(() => {
        const field = document.querySelector(".magnitude-filter-values").getBoundingClientRect();
        const input = document.querySelector("[data-slot=combobox-chip-input]").getBoundingClientRect();
        return input.x >= field.x - 1 && input.right <= field.right + 1;
      });
      const bounds = await input.boundingBox();
      const viewport = await page.locator(".magnitude-filter-values").boundingBox();
      assert.ok(bounds.x >= viewport.x - 1 && bounds.x + bounds.width <= viewport.x + viewport.width + 1,
        "Adding a chip keeps the Add range input fully visible");
    }
    assert.equal(await chips.count(), 5);
    await page.waitForTimeout(350);
    await page.waitForFunction(() => document.querySelectorAll(".event-row-skeleton").length === 0);
    const fieldBounds = await page.locator(".magnitude-filter-field").boundingBox();
    const chevronBounds = await chevron.boundingBox();
    assert.equal(fieldBounds.height, 52, "Selected chips keep the account-sized mobile field at one row");
    const scroll = await page.locator(".magnitude-filter-values").evaluate((element) => {
      const overflow = element.scrollWidth > element.clientWidth;
      element.scrollLeft = 100;
      return { overflow, offset: element.scrollLeft, scrollbar: getComputedStyle(element).scrollbarWidth };
    });
    assert.ok(scroll.overflow && scroll.offset > 0, "Chips scroll horizontally inside the field");
    assert.equal(scroll.scrollbar, "none");
    assert.ok(fieldBounds.x + fieldBounds.width - chevronBounds.x - chevronBounds.width <= 20,
      "Chevron stays at the right edge while chips scroll");
    await page.screenshot({ path: ".astro/magnitude-verification/mobile.png" });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.locator(".search-field input").click();
    await input.click();

    await page.getByRole("option", { name: "All magnitudes", exact: true }).click();
    await input.fill("Above M6.0");
    await input.press("ArrowDown");
    await input.press("Enter");
    assert.equal(await chips.count(), 1);
    await input.press("Backspace");
    assert.equal(await chips.count(), 0);
    assert.equal(await input.getAttribute("placeholder"), "Search ranges");
    await page.locator(".search-field input").click();
    assert.equal(await input.getAttribute("placeholder"), "All magnitudes");
    assert.deepEqual(errors, []);
    console.log("PASS: default text, focus behavior, exclusive All magnitudes, searchable bands, debounced apply without blur, skeleton loading, unchanged subtitle, stale-response protection, pagination, chip removal, keyboard, and mobile layout");
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
