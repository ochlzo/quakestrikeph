// node --experimental-strip-types scripts/forecast-clustering/compare-reference.mjs [--browser-url URL]
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, writeFile, mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import { clusterCatalog, windowEvents } from "../../src/features/forecast-prototype/clustering.ts";

const here = dirname(fileURLToPath(import.meta.url));
const app = resolve(here, "../..");
const option = name => {
  const index = process.argv.indexOf(name);
  if (index < 0) return undefined;
  if (!process.argv[index + 1]) throw new Error(`Missing value for ${name}`);
  return process.argv[index + 1];
};
const reference = resolve(option("--reference-project") ?? join(app, "../../../quakestrikeph-zaliapin-clustering-corrected"));
const browserUrl = option("--browser-url");
const fixturePath = join(app, "src/features/forecast-prototype/fixtures/sample-catalog.json");
const fixtureBytes = await readFile(fixturePath);
const fixture = JSON.parse(fixtureBytes);
const output = await mkdtemp(join(tmpdir(), "quakestrike-clustering-reference-"));
const executable = join(output, process.platform === "win32" ? "reference.exe" : "reference");
const sources = [join(here, "reference.cpp"), join(reference, "diagnose/src/diagnose.cpp"),
  join(reference, "cluster/src/cluster.cpp")];
const digest = bytes => createHash("sha256").update(bytes).digest("hex");
const hashes = {};
for (const source of sources) hashes[source] = digest(await readFile(source));
for (const header of ["common/include/zaliapin/common/event.hpp", "diagnose/include/zaliapin/diagnose/diagnose.hpp",
  "cluster/include/zaliapin/cluster/cluster.hpp"]) hashes[join(reference, header)] = digest(await readFile(join(reference, header)));

function command(program, args, input) {
  const result = spawnSync(program, args, { input, encoding: "utf8", timeout: 120000, windowsHide: true });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${program} failed (${result.status}): ${result.stderr || result.stdout}`);
  return result.stdout;
}
command(option("--compiler") ?? "g++", ["-std=c++17", "-O2", "-Wno-unknown-pragmas",
  ...["common/include", "diagnose/include", "cluster/include"].flatMap(path => ["-I", join(reference, path)]),
  ...sources, "-o", executable]);

function nativeRows(scenario, settings) {
  const input = [settings.minimumMagnitude, settings.b, settings.fractalDimension, settings.distanceFloorKm,
    settings.eta0, scenario.events.length].join(" ") + "\n" + scenario.events.map(event =>
    [event.eventId, event.timeSeconds, event.timePrecision, event.latitude, event.longitude, event.depthKm,
      event.magnitude].join(" ")).join("\n") + "\n";
  const csv = command(executable, [], input);
  const [header, ...lines] = csv.trim().split(/\r?\n/);
  const keys = header.split(",");
  return { csv, rows: lines.map(line => Object.fromEntries(line.split(",").map((value, i) => [keys[i], value]))) };
}
const numeric = value => value === "" ? null : value === "-inf" ? -Infinity : Number(value);
let maxScoreDifference = 0;
function verify(actual, expected, label) {
  assert.equal(actual.assignments.length, expected.length, `${label}: included events`);
  for (let i = 0; i < expected.length; i++) {
    const a = actual.assignments[i], e = expected[i];
    assert.equal(a.event.eventId, e.eventId, `${label}: event order`);
    assert.equal(a.parentId, e.parentId || null, `${label}/${e.eventId}: parent`);
    assert.equal(a.linkType, e.linkType, `${label}/${e.eventId}: threshold classification`);
    assert.equal(a.groupId, Number(e.groupId), `${label}/${e.eventId}: group`);
    assert.equal(a.groupSize, Number(e.groupSize), `${label}/${e.eventId}: group size`);
    for (const key of ["log10Eta", "measuredDistanceKm", "effectiveDistanceKm"]) {
      const value = numeric(e[key]);
      if (value === null || !Number.isFinite(value)) assert.equal(a[key], value, `${label}/${e.eventId}: ${key}`);
      else {
        const difference = Math.abs(a[key] - value);
        assert.ok(difference <= 1e-10 * Math.max(1, Math.abs(value)), `${label}/${e.eventId}: ${key} differs by ${difference}`);
        if (key === "log10Eta") maxScoreDifference = Math.max(maxScoreDifference, difference);
      }
    }
  }
}
function nativeWindow(rows, scenario) {
  const byId = new Map(scenario.events.map(event => [event.eventId, event]));
  const anchor = byId.get(scenario.anchorId);
  const group = rows.find(row => row.eventId === scenario.anchorId).groupId;
  return rows.filter(row => {
    const event = byId.get(row.eventId);
    const ordered = event.timeSeconds > anchor.timeSeconds &&
      ((event.timePrecision === "second" && anchor.timePrecision === "second") ||
        Math.floor(event.timeSeconds / 60) !== Math.floor(anchor.timeSeconds / 60));
    return row.groupId === group && event.magnitude >= 1 && ordered && event.timeSeconds <= anchor.timeSeconds + 86400;
  }).map(row => row.eventId);
}

const cases = [];
for (const scenario of fixture.scenarios) {
  const settings = scenario.settings ?? fixture.settings;
  const native = nativeRows(scenario, settings);
  const started = performance.now();
  const actual = clusterCatalog(scenario.events, settings);
  const elapsed = performance.now() - started;
  verify(actual, native.rows, scenario.id);
  verify(clusterCatalog([...scenario.events].reverse(), settings), native.rows, `${scenario.id}/reversed`);
  const eventIds = windowEvents(actual, scenario.anchorId).map(row => row.event.eventId);
  assert.deepEqual(eventIds, nativeWindow(native.rows, scenario), `${scenario.id}: native window membership`);
  if (scenario.expectedWindowEventIds) assert.deepEqual(eventIds, scenario.expectedWindowEventIds, `${scenario.id}: explicit expected window`);
  if (scenario.id === "threshold-equality") assert.equal(actual.assignments[1].linkType, "weak");
  if (scenario.id === "mixed-precision-and-ties") {
    assert.equal(actual.assignments.find(row => row.event.eventId === "second-child").parentId, "second-a");
  }
  if (scenario.id === "branches-and-boundaries") {
    assert.equal(actual.assignments.find(row => row.event.eventId === "later-b").parentId, "earlier-p");
    assert.equal(actual.assignments.find(row => row.event.eventId === "later-c").parentId, "later-b");
    assert.equal(windowEvents(actual, scenario.anchorId, 0).length, 0);
    assert.deepEqual(windowEvents(actual, scenario.anchorId, 1).map(row => row.event.eventId), ["later-b"]);
    const anchor = scenario.events.find(event => event.eventId === scenario.anchorId);
    const shortened = { ...scenario, events: scenario.events.filter(event => event.timeSeconds >= anchor.timeSeconds) };
    const shortenedNative = nativeRows(shortened, settings);
    const shortenedResult = clusterCatalog(shortened.events, settings);
    verify(shortenedResult, shortenedNative.rows, "missing-earlier-history");
    assert.deepEqual(windowEvents(shortenedResult, scenario.anchorId).map(row => row.event.eventId), []);
    await writeFile(join(output, "missing-earlier-history.reference.csv"), shortenedNative.csv);
    console.log("PASS missing-earlier-history: removing the earlier parent changes the window count from 3 to 0");
  }
  await writeFile(join(output, `${scenario.id}.reference.csv`), native.csv);
  cases.push({ scenario: scenario.id, inputEvents: scenario.events.length, includedEvents: actual.assignments.length,
    windowEventIds: eventIds, nodeComputationMs: elapsed, browserComputationMs: null });
  console.log(`PASS ${scenario.id}: ${actual.assignments.length} assignments, ${eventIds.length} window events`);
}

// Repeat the generated catalog with the recorded raw-distance variant.
const generated = fixture.scenarios.find(scenario => scenario.id === "deterministic-catalog");
const rawSettings = { ...fixture.settings, distanceFloorKm: 0, eta0: 8.252215477113915e-5 };
const rawNative = nativeRows(generated, rawSettings);
verify(clusterCatalog(generated.events, rawSettings), rawNative.rows, "deterministic-catalog/raw");
await writeFile(join(output, "deterministic-catalog-raw.reference.csv"), rawNative.csv);
assert.deepEqual(clusterCatalog([], fixture.settings).assignments, []);
const event = fixture.scenarios[0].events[0];
assert.throws(() => clusterCatalog([event, event]), /Duplicate/);
assert.throws(() => clusterCatalog([{ ...event, latitude: NaN }]), /Invalid/);
assert.throws(() => clusterCatalog([event], { ...fixture.settings, eta0: 0 }), /settings/);
assert.throws(() => clusterCatalog([event], {}), /settings/);

// Appending a strictly later batch preserves previous parents; late arrivals require a fresh full computation.
const chronological = [...generated.events].sort((a, b) => a.timeSeconds - b.timeSeconds);
const prefix = clusterCatalog(chronological.slice(0, 64), fixture.settings);
const full = clusterCatalog(chronological, fixture.settings);
assert.deepEqual(full.assignments.slice(0, 64).map(row => [row.parentId, row.linkType, row.rootEventId]),
  prefix.assignments.map(row => [row.parentId, row.linkType, row.rootEventId]));
const lateScenario = { ...generated, events: [...generated.events, { ...event,
  eventId: "late-arrival", timeSeconds: chronological[32].timeSeconds + 15, magnitude: 6 }] };
const lateNative = nativeRows(lateScenario, fixture.settings);
verify(clusterCatalog(lateScenario.events, fixture.settings), lateNative.rows, "late-arrival/full-recompute");
await writeFile(join(output, "late-arrival.reference.csv"), lateNative.csv);
const correctedScenario = { ...generated, events: generated.events.map((row, index) =>
  index === 64 ? { ...row, magnitude: 7, latitude: 16, longitude: 121 } : row) };
const correctedNative = nativeRows(correctedScenario, fixture.settings);
verify(clusterCatalog(correctedScenario.events, fixture.settings), correctedNative.rows, "correction/full-recompute");
await writeFile(join(output, "correction.reference.csv"), correctedNative.csv);
console.log("PASS chronological append, late arrival, and corrected observation checks");

let browserDescription = null;
if (browserUrl) {
  const require = createRequire(import.meta.url);
  const { chromium } = require(option("--playwright-module") ?? "playwright");
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(browserUrl);
    await page.waitForFunction(() => !!window.forecastClusteringExperiment);
    for (let i = 0; i < fixture.scenarios.length; i++) {
      const scenario = fixture.scenarios[i], settings = scenario.settings ?? fixture.settings;
      const reply = await page.evaluate(data => window.forecastClusteringExperiment.run(data),
        { events: scenario.events, settings, anchorId: scenario.anchorId, requestId: scenario.id });
      assert.equal(reply.ok, true, reply.error);
      verify(reply.result, nativeRows(scenario, settings).rows, `${scenario.id}/browser-worker`);
      assert.deepEqual(reply.windowEventIds, cases[i].windowEventIds);
      cases[i].browserComputationMs = reply.computationMs;
    }
    const failure = await page.evaluate(data => window.forecastClusteringExperiment.run(data),
      { events: [event, event], settings: fixture.settings, anchorId: event.eventId, requestId: "duplicate" });
    assert.equal(failure.ok, false);
    assert.match(failure.error, /Duplicate/);
    for (const [width, height, scenarioId, rows, count] of [
      [1280, 800, "branches-and-boundaries", 7, 3],
      [390, 844, "mixed-precision-and-ties", 6, 2],
    ]) {
      await page.setViewportSize({ width, height });
      await page.selectOption("#scenario", scenarioId);
      await page.click("#run");
      await page.waitForFunction(() => !document.querySelector("#run").disabled);
      assert.equal(await page.locator("#assignments tr").count(), rows);
      assert.match(await page.locator("#window").innerText(), new RegExp(`window: ${count}\\.`));
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
        "The table's horizontal overflow must remain inside its wrapper.");
    }
    assert.deepEqual(errors, []);
    browserDescription = { version: browser.version(), userAgent: await page.evaluate(() => navigator.userAgent),
      physicalPhoneTested: false };
    console.log("PASS Chromium module worker: all sample cases, duplicate-error reply, and desktop/mobile-sized harness controls");
  } finally { await browser.close(); }
}
const report = {
  scope: "Synthetic sample parity only. No full-catalog equivalence or physical phone performance claim.",
  fixtureSha256: digest(fixtureBytes), referenceSourceSha256: hashes, settings: fixture.settings,
  nodeVersion: process.version, browser: browserDescription, maxLog10ScoreDifference: maxScoreDifference,
  cases, generatedRawComparisonPassed: true, missingHistoryCounterexample: { fullCount: 3, shortenedCount: 0 },
  chronologicalAppendCheckPassed: true, lateArrivalFullRecomputePassed: true, correctionFullRecomputePassed: true,
};
await writeFile(join(output, "report.json"), JSON.stringify(report, null, 2) + "\n");
if (option("--evidence")) {
  // Portable evidence excludes machine-specific source paths. Native CSV artifacts remain in the fresh temporary run.
  const portable = { ...report, referenceSourceSha256: Object.fromEntries(Object.entries(hashes).map(([path, hash]) =>
    [path.startsWith(reference) ? `corrected-clustering/${path.slice(reference.length + 1).replaceAll("\\", "/")}` :
      "bulletin/scripts/forecast-clustering/reference.cpp", hash])) };
  portable.implementationSourceSha256 = {};
  for (const file of ["clustering.ts", "clustering.worker.ts", "experiment.ts"]) {
    portable.implementationSourceSha256[file] = digest(await readFile(join(app, "src/features/forecast-prototype", file)));
  }
  await writeFile(resolve(option("--evidence")), JSON.stringify(portable, null, 2) + "\n");
}
console.log(`Reference evidence: ${join(output, "report.json")}`);
