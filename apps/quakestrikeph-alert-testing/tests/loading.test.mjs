import assert from "node:assert/strict";
import { test } from "node:test";
import { estimatedProgress, isLoading, trackLoading } from "../src/lib/loading.ts";

test("background work does not activate or prolong visible loading", async () => {
  let finishBackground, finishVisible;
  const background = trackLoading(() => new Promise(resolve => { finishBackground = resolve; }), false);
  assert.equal(isLoading(), false);
  const visible = trackLoading(() => new Promise(resolve => { finishVisible = resolve; }));
  assert.equal(isLoading(), true);
  finishVisible();
  await visible;
  assert.equal(isLoading(), false);
  finishBackground();
  await background;
  assert.equal(isLoading(), false);
});

test("estimated progress advances more slowly and never claims completion", () => {
  const start = estimatedProgress(0);
  const next = estimatedProgress(250);
  const later = estimatedProgress(500);
  assert.ok(Math.abs(start - 0.08) < 0.000001);
  assert.ok(next > start);
  assert.ok(later > next);
  assert.ok(later - next < next - start);
  assert.ok(estimatedProgress(100000) <= 0.94);
  assert.ok(estimatedProgress(8000) > 0.92);
  assert.ok(estimatedProgress(251) > next);
  assert.ok(estimatedProgress(251) - next < 0.001);
  assert.ok(Math.abs(estimatedProgress(0, 0.7) - 0.7) < 0.000001);
});

test("loading continues until overlapping requests finish", async () => {
  let finishFirst, finishSecond;
  const first = trackLoading(() => new Promise(resolve => { finishFirst = resolve; }));
  const second = trackLoading(() => new Promise(resolve => { finishSecond = resolve; }));
  assert.equal(isLoading(), true);
  finishFirst();
  await first;
  assert.equal(isLoading(), true);
  finishSecond();
  await second;
  assert.equal(isLoading(), false);
});

test("rejected requests do not leave the bar running", async () => {
  await assert.rejects(trackLoading(async () => { throw new Error("Connection failed"); }));
  assert.equal(isLoading(), false);
});
