// Run with the dev server running: node tests/magnitude-filter.cjs (requires Playwright).
const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1024, height: 768 } });
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
    await page.goto(`${process.env.BULLETIN_URL || "http://localhost:4321"}?date=custom&from=2026-08-31T16%3A00%3A00.000Z&to=2026-10-31T16%3A00%3A00.000Z`);
    await page.locator('astro-island[component-url*=Bulletin][ssr]').waitFor({ state: "detached" });
    const trigger = page.locator(".filter-bar .magnitude-filter-field");
    const labels = page.locator(".magnitude-filter-value");
    const chevron = page.locator('.filter-bar .magnitude-filter-field > svg:last-child');
    const rows = page.locator(".event-row-v2:not(.event-row-skeleton)");
    await rows.filter({ hasText: "Sample location 0" }).first().waitFor();
    const initialCount = requests.length;
    assert.equal(await labels.textContent(), "All magnitudes");
    assert.equal(await trigger.textContent(), "All magnitudes");
    assert.equal(await chevron.evaluate((element) => getComputedStyle(element).transform), "none");
    assert.equal(await page.locator('[aria-label="Clear magnitude selections"]').count(), 0);
    assert.equal(await page.locator(".filter-bar .magnitude-filter-field > svg").count(), 1);
    assert.equal(await page.locator(".date-filter-trigger > svg").count(), 1);
    const dateLabel = page.locator(".date-filter-trigger .filter-value-text");
    assert.equal(await dateLabel.getAttribute("title"), "Sep 1 - Oct 31, 2026");
    assert.equal(await dateLabel.evaluate((element) => element.lastChild.textContent), "Sep 1 - Oct 31",
      "The custom date label shortens at 1024px while retaining the complete date in its title");
    assert.equal((await page.locator(".date-filter-trigger").boundingBox()).height, 52);
    await page.locator(".date-filter-trigger").click();
    const customOption = page.getByRole("option", { name: "Sep 1 - Oct 31, 2026", exact: true });
    const customSpacing = await customOption.evaluate((element) => {
      const check = element.lastElementChild.getBoundingClientRect();
      const range = document.createRange();
      range.selectNodeContents(element.firstElementChild);
      return check.left - range.getBoundingClientRect().right;
    });
    assert.ok(customSpacing >= 8, "The custom date label leaves space before its checkmark");
    await mkdir(".astro/magnitude-verification", { recursive: true });
    await page.screenshot({ path: ".astro/magnitude-verification/date.png" });
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

    await trigger.click();
    const magnitudeOption = page.getByRole("option").first();
    await magnitudeOption.hover();
    assert.equal(await magnitudeOption.evaluate((element) => getComputedStyle(element).backgroundColor), dateHoverColor);
    assert.equal(await trigger.textContent(), "All magnitudes");
    await page.waitForTimeout(200);
    assert.equal(await chevron.evaluate((element) => getComputedStyle(element).transform), "matrix(-1, 0, 0, -1, 0, 0)");
    assert.equal(await page.getByRole("option").count(), 6);
    assert.equal(await page.getByRole("option").first().textContent(), "All magnitudes");
    assert.equal(await page.getByRole("option").first().getAttribute("aria-selected"), "true");
    await page.getByRole("option", { name: "All magnitudes", exact: true }).click();
    assert.equal(await labels.textContent(), "All magnitudes");
    assert.equal(await trigger.textContent(), "All magnitudes");
    await page.clock.install();
    await page.clock.pauseAt(new Date(Date.now() + 1000));
    holdNextResponse = true;
    await page.getByRole("option", { name: "Below M3.0", exact: true }).click();
    await page.clock.runFor(150);
    await page.getByRole("option", { name: "M5.0 - M5.9", exact: true }).click();
    await page.clock.runFor(150);
    await page.getByRole("option", { name: "Above M6.0", exact: true }).click();
    assert.equal(await labels.textContent(), "3 selected");
    assert.equal(await labels.filter({ hasText: "All magnitudes" }).count(), 0);
    await page.clock.runFor(299);
    assert.equal(requests.length, initialCount, "Each selection resets the 300 ms debounce");
    await page.clock.runFor(1);
    await page.clock.resume();
    await page.waitForTimeout(100);
    assert.equal(requests.length, initialCount + 1, "One request applies the final selection without blur");
    assert.ok(await page.locator('.magnitude-filter-popover').isVisible());
    assert.equal(await rows.count(), 0, "Hide previous results during refresh");
    assert.equal(await page.locator(".event-row-skeleton").count(), 6);
    assert.equal(await page.locator("#events-title").textContent(), "Earthquakes");
    assert.equal(await page.getByText("Updating earthquakes…", { exact: true }).count(), 0);
    assert.equal(await page.locator(".event-list-skeleton").getAttribute("aria-busy"), "true");
    releaseResponse();
    await page.waitForFunction(() => document.querySelector('#event-list')?.getAttribute('aria-busy') === 'false');

    // Each dot shares its map legend color, in the dropdown.
    for (const className of ["mag-under-3", "mag-5", "mag-6"]) {
      const color = await page.locator(`.map-legend .${className}`).evaluate(
        (element) => getComputedStyle(element).backgroundColor,
      );
      assert.equal(await page.locator(`.magnitude-filter-popover .${className}`).evaluate(
        (element) => getComputedStyle(element).backgroundColor,
      ), color);
    }
    await page.screenshot({ path: ".astro/magnitude-verification/desktop.png" });

    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
    assert.equal(requests.length, initialCount + 1, "Blur must not trigger another request");
    assert.equal(await chevron.evaluate((element) => getComputedStyle(element).transform), "none");
    await page.waitForFunction(() => document.querySelectorAll(".event-row-skeleton").length === 0);
    assert.deepEqual(requests.at(-1).magnitudeRanges, [
      { from: 6 }, { from: 5, below: 6 }, { below: 3 },
    ]);
    assert.equal(await rows.count(), 2);
    await page.getByLabel("Go to next page").click();
    await page.getByText("Page 2", { exact: true }).waitFor();
    assert.equal(await rows.count(), 2);
    assert.deepEqual(requests.at(-1).magnitudeRanges, requests.at(-2).magnitudeRanges);
    assert.equal(requests.at(-1).cursor, "2");

    await trigger.click();
    const beforeRemove = requests.length;
    await page.getByRole("option", { name: "Above M6.0", exact: true }).click();
    assert.equal(await labels.textContent(), "2 selected");
    await page.waitForTimeout(350);
    assert.equal(requests.length, beforeRemove + 1, "Deselecting a range applies without closing");
    await trigger.press("Escape");
    await trigger.focus();
    await trigger.press("Tab");
    await page.waitForFunction(() => document.querySelectorAll(".event-row-skeleton").length === 0);
    assert.deepEqual(requests.at(-1).magnitudeRanges, [{ from: 5, below: 6 }, { below: 3 }]);

    await trigger.click();
    const beforeAll = requests.length;
    await page.getByRole("option", { name: "All magnitudes", exact: true }).click();
    assert.equal(await labels.textContent(), "All magnitudes");
    assert.equal(await trigger.textContent(), "All magnitudes");
    assert.equal(await page.getByRole("option", { selected: true }).count(), 1);
    await page.waitForTimeout(350);
    assert.equal(requests.length, beforeAll + 1, "All magnitudes applies without blur");
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => document.querySelectorAll(".event-row-skeleton").length === 0);
    assert.equal(requests.at(-1).magnitudeRanges, undefined);
    assert.equal(await trigger.textContent(), "All magnitudes");

    // A slow response for an earlier selection must not replace newer results.
    await trigger.click();
    holdNextResponse = true;
    const beforeSlow = requests.length;
    await page.getByRole("option", { name: "M4.0 - M4.9", exact: true }).click();
    await page.waitForTimeout(350);
    assert.equal(requests.length, beforeSlow + 1);
    const releaseSlowResponse = releaseResponse;
    await page.getByRole("option", { name: "All magnitudes", exact: true }).click();
    await page.getByRole("option", { name: "Above M6.0", exact: true }).click();
    await page.waitForTimeout(350);
    assert.deepEqual(requests.at(-1).magnitudeRanges, [{ from: 6 }]);
    await page.waitForFunction(() => document.querySelector('#event-list')?.getAttribute('aria-busy') === 'false');
    assert.deepEqual(await rows.locator('.row-v2-measure strong').allTextContents(), ['M6.0', 'M7.0']);
    releaseSlowResponse();
    await page.waitForTimeout(150);
    assert.deepEqual(await rows.locator('.row-v2-measure strong').allTextContents(), ['M6.0', 'M7.0'],
      "A stale response must not overwrite the latest magnitude results");
    await page.getByRole("option", { name: "All magnitudes", exact: true }).click();
    await page.waitForTimeout(350);
    await page.keyboard.press("Escape");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: "Show earthquakes" }).click();
    await page.getByRole("dialog", { name: "Selected earthquake and earthquake search" }).waitFor();
    await trigger.click();
    for (const name of ["Below M3.0", "M3.0 - M3.9", "M4.0 - M4.9", "M5.0 - M5.9", "Above M6.0"]) {
      await page.getByRole("option", { name, exact: true }).click();
    }
    assert.equal(await labels.textContent(), "5 selected");
    await page.waitForTimeout(350);
    await page.waitForFunction(() => document.querySelectorAll(".event-row-skeleton").length === 0);
    const fieldBounds = await page.locator(".filter-bar .magnitude-filter-field").boundingBox();
    const chevronBounds = await chevron.boundingBox();
    assert.equal(fieldBounds.height, 52, "Selected labels keep the mobile field at one row");
    const overflow = await page.locator(".magnitude-filter-values").evaluate((element) => {
      element.style.maxWidth = "40px";
      element.scrollLeft = element.scrollWidth;
      const result = {
        offset: element.scrollLeft,
        style: getComputedStyle(element).overflowX,
        scrollbar: getComputedStyle(element).scrollbarWidth,
      };
      element.style.maxWidth = "";
      return result;
    });
    assert.ok(overflow.offset > 0, "The summary scrolls horizontally when wider than the field");
    assert.equal(overflow.style, "auto");
    assert.equal(overflow.scrollbar, "none");
    assert.ok(fieldBounds.x + fieldBounds.width - chevronBounds.x - chevronBounds.width <= 20,
      "Chevron stays at the right edge while labels are clipped");
    await page.screenshot({ path: ".astro/magnitude-verification/mobile.png" });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.keyboard.press("Escape");
    await page.locator(".search-field input").click();
    await trigger.click();

    await page.getByRole("option", { name: "All magnitudes", exact: true }).click();
    await page.getByRole("option", { name: "Above M6.0", exact: true }).focus();
    await page.keyboard.press("Enter");
    assert.equal(await labels.count(), 1);
    assert.equal(await labels.textContent(), "Above M6.0");
    await page.keyboard.press("Enter");
    assert.equal(await labels.textContent(), "All magnitudes");
    assert.equal(await trigger.textContent(), "All magnitudes");
    await page.keyboard.press("Escape");
    await page.locator(".search-field input").click();
    assert.equal(await trigger.textContent(), "All magnitudes");
    assert.deepEqual(errors, []);
    console.log("PASS: default text, dropdown behavior, exclusive All magnitudes, debounced apply without closing, skeleton loading, stale-response protection, pagination, deselection, keyboard, and scrollable summaries and mobile layout");
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
