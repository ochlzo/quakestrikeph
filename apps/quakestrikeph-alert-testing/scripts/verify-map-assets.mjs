import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";

const assets = new URL("../dist/_astro/", import.meta.url);
const workers = readdirSync(assets).filter(name => /^map-worker-.*\.js$/.test(name));
assert.equal(workers.length, 1, "The build must emit one map worker");
assert.ok(readFileSync(new URL(workers[0], assets), "utf8").trim(),
  "MapLibre worker initialization must survive production tree shaking");
const places = JSON.parse(readFileSync(new URL("../dist/assets/accounts/philippine-places.json", import.meta.url), "utf8"));
assert.ok(Array.isArray(places) && places.length > 0, "The build must include the places index");
console.log("Production map worker and places index verified.");
