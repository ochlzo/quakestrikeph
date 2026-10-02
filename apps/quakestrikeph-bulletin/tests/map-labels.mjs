// node --experimental-strip-types tests/map-labels.mjs
import assert from "node:assert/strict";
import { VectorTile } from "@mapbox/vector-tile";
import { fromGeojsonVt } from "@maplibre/vt-pbf";
import { PbfReader } from "pbf";
import { cleanMapLabel, englishMapLabel, cleanMapStyle } from "../src/lib/map-labels.ts";
import { cleanLabelTile, labelProtocol, loadLabelTile, transformLabelRequest } from "../src/lib/map-label-tiles.ts";
import { cacheLabelTile, labelCacheName } from "../src/lib/map-label-cache.ts";

assert.equal(cleanMapLabel("  Peña-Blanca  (Mt. 12) / 山 🗻\n"), "PeñaBlanca Mt 12");
assert.equal(cleanMapLabel("Peña NIÑO!"), "Peña NIÑO");
assert.equal(cleanMapLabel("Pen\u0303a NIN\u0303O"), "Peña NIÑO");
assert.equal(cleanMapLabel("Mayón / Ññ"), "Mayon Ññ");
assert.equal(cleanMapLabel("A\tB\nC — D!"), "A B C D");
assert.equal(cleanMapLabel("北京 ⚑ !"), "");
assert.equal(cleanMapLabel(null), "");
assert.equal(englishMapLabel({ "name:en": "Beijing", "name:latin": "Peking", name: "北京" }), "Beijing");
assert.equal(englishMapLabel({ name_en: "!!!", "name:latin": "Baguio (City)", name: "Other" }), "Baguio City");
assert.equal(englishMapLabel({ name: "Davao City!" }), "Davao City");
assert.equal(englishMapLabel({ name: "北京" }), "");

const style = { version: 8, sources: { openmaptiles: { type: "vector", tiles: [] } }, layers: [
  { id: "country", type: "symbol", source: "openmaptiles", layout: { "text-field": ["get", "name"], "text-size": 14 }, paint: { "text-color": "#123" } },
  { id: "road-shield", type: "symbol", source: "openmaptiles", layout: { "text-field": ["get", "ref"] } },
  { id: "icon", type: "symbol", source: "openmaptiles", layout: { "icon-image": "airport" } },
  { id: "water", type: "fill", source: "openmaptiles", paint: { "fill-color": "#74A9D9" } },
] };
const originalStyle = structuredClone(style);
const cleanedStyle = cleanMapStyle(style);
assert.deepEqual(style, originalStyle, "Original style is not mutated");
assert.deepEqual(cleanedStyle.layers[0].layout["text-field"], ["coalesce", ["get", "qs_name"], ""]);
assert.deepEqual(cleanedStyle.layers[1].layout["text-field"], ["coalesce", ["get", "qs_ref"], ""]);
assert.deepEqual(cleanedStyle.layers[0].paint, style.layers[0].paint);
assert.equal(cleanedStyle.layers[0].layout["text-size"], 14);
assert.deepEqual(cleanedStyle.layers.slice(2), style.layers.slice(2));

const url = "https://tiles.openfreemap.org/planet/snapshot/5/26/14.pbf";
assert.deepEqual(transformLabelRequest(url, "Tile"), { url: `${labelProtocol}://${url}` });
for (const untouched of ["https://tiles.mapterhorn.com/5/26/14.webp", "https://tiles.openfreemap.org/natural_earth/5/26/14.png", "https://other.example/5/26/14.pbf"]) {
  assert.equal(transformLabelRequest(untouched, "Tile"), undefined);
}
assert.equal(transformLabelRequest(url, "Source"), undefined);

const bytes = fromGeojsonVt({
  place: { features: [
    { id: 42, type: 1, geometry: [[12, 34]], tags: { name: "北京", name_en: "Beijing!", class: "city", rank: 2 } },
    { id: 43, type: 1, geometry: [[56, 78]], tags: { name: "山!" } },
  ] },
  transportation_name: { features: [{ id: 0, type: 2, geometry: [[[1, 2], [3, 4]]], tags: { ref: "AH-26", name: "Peña Rd.", class: "motorway" } }] },
  water: { features: [{ id: 7, type: 3, geometry: [[[0, 0], [10, 0], [10, 10], [0, 0]]], tags: { class: "ocean", intermittent: 0 } }] },
}, { version: 2, extent: 4096 });
const input = new Uint8Array(bytes).buffer;
const decode = (buffer) => new VectorTile(new PbfReader(buffer));
const before = decode(input);
const output = cleanLabelTile(input);
const after = decode(output);
assert.deepEqual(Object.keys(after.layers), Object.keys(before.layers));
for (const [name, layer] of Object.entries(before.layers)) {
  const cleaned = after.layers[name];
  assert.equal(cleaned.version, layer.version);
  assert.equal(cleaned.extent, layer.extent);
  assert.equal(cleaned.length, layer.length);
  for (let i = 0; i < layer.length; i++) {
    const original = layer.feature(i), result = cleaned.feature(i);
    assert.equal(result.id, original.id);
    assert.equal(result.type, original.type);
    assert.deepEqual(result.loadGeometry(), original.loadGeometry());
    for (const [key, value] of Object.entries(original.properties)) assert.equal(result.properties[key], value);
  }
}
assert.equal(after.layers.place.feature(0).properties.qs_name, "Beijing");
assert.equal(after.layers.place.feature(1).properties.qs_name, "");
assert.equal(after.layers.transportation_name.feature(0).properties.qs_ref, "AH26");
assert.equal(after.layers.transportation_name.feature(0).properties.qs_name, "Peña Rd");
assert.deepEqual(after.layers.water.feature(0).properties, before.layers.water.feature(0).properties);

const originalFetch = globalThis.fetch;
const controller = new AbortController();
try {
  globalThis.fetch = async (requested, options) => {
    assert.equal(requested, url);
    assert.equal(options.signal, controller.signal);
    assert.equal(options.headers.Accept, "application/x-protobuf");
    return new Response(input, { headers: { "Cache-Control": "max-age=86400" } });
  };
  const response = await loadLabelTile({ url: `${labelProtocol}://${url}`, headers: { Accept: "application/x-protobuf" } }, controller);
  assert.equal(response.cacheControl, "max-age=86400");
  assert.equal(decode(response.data).layers.place.feature(0).properties.qs_name, "Beijing");
  globalThis.fetch = async () => new Response(null, { status: 503 });
  await assert.rejects(loadLabelTile({ url: `${labelProtocol}://${url}` }, controller), /HTTP 503/);
  globalThis.fetch = async (_requested, options) => { options.signal.throwIfAborted(); return new Response(input); };
  controller.abort();
  await assert.rejects(loadLabelTile({ url: `${labelProtocol}://${url}` }, controller), { name: "AbortError" });
} finally {
  globalThis.fetch = originalFetch;
}
// Cache Storage is browser-owned; exercise the loader with a small in-memory implementation.
const originalCaches = Object.getOwnPropertyDescriptor(globalThis, "caches");
const entries = new Map();
let failRead = false, failWrite = false, failOpen = false;
const cache = {
  async match(key) { if (failRead) throw new Error("Cache read blocked"); return entries.get(String(key))?.clone(); },
  async put(key, response) { if (failWrite) throw new Error("Quota exceeded"); entries.set(String(key), response.clone()); },
  async keys() { return [...entries.keys()].map((key) => new Request(key)); },
  async delete(key) { return entries.delete(typeof key === "string" ? key : key.url); },
};
try {
  Object.defineProperty(globalThis, "caches", { configurable: true, value: {
    async open(name) { assert.equal(name, labelCacheName); if (failOpen) throw new Error("Storage blocked"); return cache; },
  } });
  let fetches = 0;
  globalThis.fetch = async () => { fetches++; return new Response(input, { headers: {
    "Cache-Control": "public, max-age=86400", "Content-Encoding": "gzip",
  } }); };
  const request = { url: `${labelProtocol}://${url}` };
  const first = await loadLabelTile(request, new AbortController());
  const second = await loadLabelTile(request, new AbortController());
  assert.equal(fetches, 1, "Cleaned cache hit bypasses downloading and transforming the tile");
  assert.deepEqual(new Uint8Array(second.data), new Uint8Array(first.data));
  assert.equal(decode(second.data).layers.transportation_name.feature(0).properties.qs_name, "Peña Rd");
  assert.equal(entries.get(url).headers.get("Content-Encoding"), null, "Cleaned bytes are not marked as compressed");
  const cancelled = new AbortController(); cancelled.abort();
  await assert.rejects(loadLabelTile(request, cancelled), { name: "AbortError" });
  assert.equal(fetches, 1);
  failRead = true;
  await loadLabelTile(request, new AbortController());
  assert.equal(fetches, 2, "Read errors fall back to the normal tile path");
  failRead = false; failWrite = true;
  assert(await loadLabelTile({ url: `${request.url}?quota` }, new AbortController()));
  assert.equal(entries.has(`${url}?quota`), false);
  failWrite = false; failOpen = true;
  assert(await loadLabelTile({ url: `${request.url}?unavailable` }, new AbortController()));
  failOpen = false;
  const headers = new Headers({ "Cache-Control": "public, max-age=86400" });
  for (let i = 0; i < 18; i++) await cacheLabelTile(`${url}?tile=${i}`, output, headers);
  assert.equal(entries.size, 16, "Persistent cache evicts the oldest tiles");
  assert(!entries.has(`${url}?tile=0`));
  assert(entries.has(`${url}?tile=17`));
  await cacheLabelTile(`${url}?large`, new ArrayBuffer(2 * 1024 * 1024 + 1), headers);
  assert(!entries.has(`${url}?large`), "Oversized tiles are not stored");
  await cacheLabelTile(`${url}?private`, output, new Headers({ "Cache-Control": "private, no-store" }));
  assert(!entries.has(`${url}?private`), "Origin cache restrictions are respected");
} finally {
  globalThis.fetch = originalFetch;
  if (originalCaches) Object.defineProperty(globalThis, "caches", originalCaches);
  else Reflect.deleteProperty(globalThis, "caches");
}
console.log("PASS label cleanup, geometry/styles, routing, cancellation, cleaned-tile cache reuse/limits and storage failure fallback");
