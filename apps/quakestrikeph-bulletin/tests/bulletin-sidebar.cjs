// Run with a Bulletin server: node tests/bulletin-sidebar.cjs
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 900 },
      reducedMotion: "reduce",
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => {
      window.mapResizeFrames = [];
      window.checkMapResizeFrames = false;
      const contexts = new WeakMap();
      const getContext = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (...args) {
        const context = getContext.apply(this, args);
        if (args[0] === "webgl2") contexts.set(this, context);
        return context;
      };
      const width = Object.getOwnPropertyDescriptor(
        HTMLCanvasElement.prototype,
        "width",
      );
      Object.defineProperty(HTMLCanvasElement.prototype, "width", {
        ...width,
        set(value) {
          width.set.call(this, value);
          if (
            !window.checkMapResizeFrames ||
            !this.classList.contains("maplibregl-canvas")
          )
            return;
          queueMicrotask(() => {
            const gl = contexts.get(this);
            const pixel = new Uint8Array(4);
            gl.readPixels(
              Math.floor(this.width / 2),
              Math.floor(this.height / 2),
              1,
              1,
              gl.RGBA,
              gl.UNSIGNED_BYTE,
              pixel,
            );
            window.mapResizeFrames.push(pixel[3]);
          });
        },
      });
    });
    await page.goto(process.env.BULLETIN_URL || "http://localhost:4321");
    await page.locator("astro-island[ssr]").waitFor({ state: "detached" });
    const toggle = page.getByRole("button", {
      name: "Toggle sidebar",
      exact: true,
    });
    const sidebar = page.locator(
      '[data-slot="sidebar"][data-variant="floating"]',
    );
    const mapWidth = () =>
      page.locator(".map-canvas").evaluate((el) => el.clientWidth);
    await page.waitForFunction(
      () => !document.querySelector('[aria-label="3D terrain"]').disabled,
    );
    for (const width of [1440, 761]) {
      await page.setViewportSize({ width, height: 900 });
      await page.getByRole("textbox", { name: "Search by province" }).waitFor();
      const expanded = await mapWidth();
      assert.equal(await sidebar.getAttribute("data-state"), "expanded");
      await page.evaluate(() => {
        window.checkMapResizeFrames = true;
      });
      await toggle.click();
      await page.waitForFunction(
        () => document.querySelector('[data-slot="sidebar"]').inert,
      );
      assert(
        (await mapWidth()) > expanded + 300,
        "Collapsed sidebar gives the map more width",
      );
      await page.waitForFunction(() => {
        const map = document.querySelector(".map-canvas");
        const canvas = document.querySelector(".maplibregl-canvas");
        return Math.abs(map.clientWidth - canvas.clientWidth) <= 1;
      });
      await toggle.click();
      assert.equal(await sidebar.getAttribute("data-state"), "expanded");
    }
    const frameAlphas = await page.evaluate(() => {
      window.checkMapResizeFrames = false;
      return window.mapResizeFrames;
    });
    assert(frameAlphas.length > 0, "The test observed canvas resizes");
    assert(
      frameAlphas.every((alpha) => alpha > 0),
      "The basemap redraws before paint after each canvas resize",
    );
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "no-preference" });
    for (let direction = 0; direction < 2; direction++) {
      const markerOffset = await page.evaluate(() => {
        const marker = document
          .querySelector(".quake-marker")
          .getBoundingClientRect();
        const map = document
          .querySelector(".map-panel")
          .getBoundingClientRect();
        return {
          x: marker.x + marker.width / 2 - (map.x + map.width / 2),
          width: marker.width,
        };
      });
      await page.evaluate(() => {
        window.mapResizeFrames = [];
        window.checkMapResizeFrames = true;
        window.sidebarMotionDone = false;
        document.querySelector('[data-slot="sidebar-gap"]').addEventListener(
          "transitionend",
          () => {
            window.sidebarMotionDone = true;
          },
          { once: true },
        );
      });
      await toggle.click();
      await page.waitForFunction(
        () =>
          window.sidebarMotionDone &&
          !document.querySelector(".map-sidebar-transition"),
      );
      await page.waitForFunction(() => {
        const map = document.querySelector(".map-canvas");
        return (
          Math.abs(map.clientWidth - map.querySelector("canvas").clientWidth) <=
          1
        );
      });
      const frames = await page.evaluate(() => window.mapResizeFrames);
      assert(
        frames.length > 0 && frames.length <= 3,
        "Animated sidebar avoids canvas resizes on every frame",
      );
      assert(
        frames.every((alpha) => alpha > 0),
        "The final redraw leaves the basemap visible",
      );
      await page.waitForFunction(({ x, width }) => {
        const marker = document
          .querySelector(".quake-marker")
          .getBoundingClientRect();
        const map = document
          .querySelector(".map-panel")
          .getBoundingClientRect();
        return (
          Math.abs(marker.x + marker.width / 2 - (map.x + map.width / 2) - x) <
            2 && Math.abs(marker.width - width) < 1
        );
      }, markerOffset);
    }
    await page.evaluate(() => {
      window.checkMapResizeFrames = false;
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page
      .getByRole("button", { name: "Show earthquakes", exact: true })
      .waitFor();
    await page.evaluate(() => {
      window.mobileSidebarMotion = [];
      window.recordMobileSidebarMotion = (event) => {
        const sheet = event.target;
        if (
          !sheet.matches('[data-mobile="true"] [data-slot="sheet-content"]') ||
          event.propertyName !== "translate"
        )
          return;
        const state = sheet.hasAttribute("data-exiting")
          ? "exiting"
          : "entering";
        const style = getComputedStyle(sheet);
        window.mobileSidebarMotion.push({
          state,
          x: sheet.getBoundingClientRect().x,
          opacity: style.opacity,
          duration: style.transitionDuration,
        });
      };
      document.addEventListener(
        "transitionrun",
        window.recordMobileSidebarMotion,
      );
    });
    await toggle.click();
    await page.waitForFunction(() =>
      window.mobileSidebarMotion.some((frame) => frame.state === "entering"),
    );
    await page.waitForFunction(() =>
      document.querySelector(
        '[data-slot="sheet-content"]:not([data-entering])',
      ),
    );
    await page.waitForFunction(
      () =>
        !document
          .querySelector('[data-slot="sheet-content"]')
          .getAnimations()
          .some((animation) => animation.playState === "running"),
    );
    await page.evaluate(() => {
      window.mobileSidebarClosingFrames = [];
      const sample = () => {
        const sheet = document.querySelector(
          '[data-mobile="true"] [data-slot="sheet-content"]',
        );
        if (!sheet) return;
        if (sheet.hasAttribute("data-exiting")) {
          let opacity = 1;
          for (let element = sheet; element; element = element.parentElement)
            opacity *= Number(getComputedStyle(element).opacity);
          window.mobileSidebarClosingFrames.push({
            opacity,
            right: sheet.getBoundingClientRect().right,
          });
        }
        requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    });
    await page
      .getByRole("button", { name: "Close navigation", exact: true })
      .click();
    await page
      .getByRole("dialog", { name: "Sidebar", exact: true })
      .waitFor({ state: "hidden" });
    const mobileMotion = await page.evaluate(() => {
      document.removeEventListener(
        "transitionrun",
        window.recordMobileSidebarMotion,
      );
      return window.mobileSidebarMotion;
    });
    assert(
      mobileMotion.find((frame) => frame.state === "entering")?.x < -250,
      "Mobile sidebar enters from fully offscreen",
    );
    assert.equal(
      mobileMotion.find((frame) => frame.state === "entering")?.duration,
      "0.5s",
      "Mobile sidebar opens over 500ms",
    );
    assert.equal(
      mobileMotion.find((frame) => frame.state === "exiting")?.duration,
      "0.3s",
      "Mobile sidebar closes over 300ms",
    );
    assert(
      mobileMotion.every((frame) => frame.opacity === "1"),
      "Mobile sidebar slides without fading",
    );
    const closingFrames = await page.evaluate(
      () => window.mobileSidebarClosingFrames,
    );
    assert(closingFrames.length > 0, "The test samples the closing slide");
    assert(
      closingFrames.every((frame) => frame.opacity === 1),
      "The drawer and its ancestors stay opaque throughout closing",
    );
    assert(
      closingFrames.at(-1).right < 10,
      "The drawer completes its offscreen slide before removal",
    );
    await page.emulateMedia({ reducedMotion: "reduce" });
    for (const width of [760, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await page
        .getByRole("button", { name: "Show earthquakes", exact: true })
        .waitFor();
      assert.equal(await page.locator(".bulletin-header nav").count(), 0);
      await toggle.click();
      const dialog = page.getByRole("dialog", { name: "Sidebar", exact: true });
      await dialog.waitFor();
      assert.equal(
        await dialog
          .getByRole("link", { name: "Earthquakes", exact: true })
          .count(),
        1,
      );
      assert.equal(
        await dialog.getByRole("link", { name: "About", exact: true }).count(),
        1,
      );
      assert.equal(await dialog.locator(".filter-bar").count(), 0);
      assert.equal(
        await dialog
          .getByRole("button", { name: "Close navigation", exact: true })
          .count(),
        1,
      );
      await dialog
        .getByRole("button", { name: "Close navigation", exact: true })
        .click();
      await dialog.waitFor({ state: "hidden" });
      await page
        .getByRole("button", { name: "Show earthquakes", exact: true })
        .click();
      await page.getByRole("textbox", { name: "Search by province" }).waitFor();
      assert.equal(
        await page.locator(".earthquake-drawer .filter-bar").count(),
        1,
      );
      await page
        .getByRole("button", { name: "Close earthquakes", exact: true })
        .click();
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
      );
    }
    assert.deepEqual(errors, []);
    console.log(
      "Bulletin sidebar: desktop collapse/map resize and mobile navigation/drawer passed.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
