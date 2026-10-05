// Run against a built/dev server: node --experimental-strip-types tests/map-worker.cjs
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

(async () => {
  const { labelCacheName } = await import("../src/lib/map-label-cache.ts");
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const errors = [];
    const tileRequests = [];
    page.on("pageerror", (error) => errors.push(error.message));
    context.on("request", (request) => {
      if (request.url().startsWith("https://tiles.openfreemap.org/planet/") && request.url().endsWith(".pbf")) {
        tileRequests.push(request.url());
      }
    });
    await page.goto(process.env.BULLETIN_URL || "http://localhost:4321");
    const waitForMap = () => page.waitForFunction(
      () => document.querySelector(".terrain-button")?.disabled === false, null, { timeout: 45000 },
    );
    await waitForMap();
    assert.equal(await page.locator('link[rel="preconnect"][href="https://tiles.openfreemap.org"]').count(), 1);
    assert.equal(await page.locator('link[rel="preload"][as="fetch"][href$="/styles/liberty"]').count(), 1);
    const workers = [];
    for (const worker of page.workers()) {
      if (await worker.evaluate(() => typeof self.addProtocol === "function")) workers.push(worker);
    }
    assert.equal(workers.length, 1, "Reuse MapLibre's worker rather than adding another worker pool");
    assert(workers[0].url().includes("map-worker"));
    assert.equal(await workers[0].evaluate(() => typeof self.addProtocol), "function", "Production bundle retains MapLibre initialization");
    const cached = await page.evaluate(async (name) => (await (await caches.open(name)).keys()).map((key) => key.url), labelCacheName);
    assert(cached.length > 0 && cached.length <= 16, "Cleaned public tiles are persisted within the cache limit");
    assert(cached.every((url) => url.startsWith("https://tiles.openfreemap.org/planet/")));
    assert(tileRequests.length > 0, "The first visit fetches public vector tiles in the worker");
    tileRequests.length = 0;
    await page.reload();
    await waitForMap();
    assert.equal(tileRequests.length, 0, "A new worker after reload reuses cleaned tiles without refetching them");
    assert.deepEqual(errors, []);
    console.log("PASS production worker startup, early resource hints, persistent cleaned-tile reuse and no page errors");
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
