// node --experimental-strip-types tests/map-landmarks.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { addLandmarkLabels, duplicateLabelIds, normalizeLabel } from "../src/lib/map-landmarks.ts";

const point = (id, name, coordinates) => ({ type: "Feature", id,
  properties: { name, category: "landmarks", minzoom: 7 }, geometry: { type: "Point", coordinates } });
assert.equal(normalizeLabel("Mt. Mayón"), normalizeLabel("Mayon Volcano"));
const candidates = [point(1, "Mount Mayon", [123.6856, 13.2574]),
  point(2, "San Jose", [120.5, 15.5]), point(3, "Missing landmark", [123, 12])];
assert.deepEqual(duplicateLabelIds(candidates, [point(4, "Mayon Volcano", [123.686, 13.258]),
  point(5, "San Jose", [121.5, 15.5])]), [1]);
assert.deepEqual(duplicateLabelIds(candidates, []), []);
assert.deepEqual(duplicateLabelIds(candidates, [{ properties: { "name:en": "Mount Mayon" },
  geometry: { type: "Point", coordinates: [123.6856, 13.2574] } }]), [1]);

const data = JSON.parse(readFileSync(new URL("../public/assets/map/philippines-landmarks.geojson", import.meta.url)));
assert.equal(data.features.length, 2264);
assert(data.features.every((feature) => feature.properties.category === "landmarks"));
assert.equal(new Set(data.features.map((feature) => feature.id)).size, data.features.length);
assert(data.features.every((feature) => feature.geometry.type === "Point"
  && feature.geometry.coordinates.every(Number.isFinite) && Number.isFinite(feature.properties.minzoom)));
assert.equal(data.metadata.license, "CC BY 4.0");

// Exercise the real installer without network or WebGL, including camera-settled callbacks.
const nativeLayers = [{ id: "native-poi", type: "symbol", "source-layer": "poi",
  layout: { "text-field": ["get", "name"], "text-font": ["Noto Sans Italic"] },
  paint: { "text-color": "#666", "text-halo-color": "#fff", "text-halo-width": 1 } }];
function mapStub() {
  return {
    layers: structuredClone(nativeLayers), source: null, supplemental: null, handlers: new Map(),
    filters: [], native: [point(4, "Mayon Volcano", [123.686, 13.258])], before: null,
    getStyle() { return { layers: this.layers }; },
    addSource(id, source) { this.source = source; },
    addLayer(layer, before) { this.supplemental = layer; this.before = before; },
    getBounds() { return { contains: () => true }; }, getZoom() { return 12; },
    queryRenderedFeatures({ layers }) { assert.deepEqual(layers, ["native-poi"]); return this.native; },
    setFilter(id, filter) { this.filters.push(filter); },
    on(event, callback) { this.handlers.set(event, callback); },
    off(event, callback) { assert.equal(this.handlers.get(event), callback); this.handlers.delete(event); },
    getLayer() { return this.supplemental; }, getSource() { return this.source; },
    removeLayer() { this.supplemental = null; }, removeSource() { this.source = null; },
  };
}
const originalFetch = globalThis.fetch;
const originalWarn = console.warn;
try {
  let fetches = 0;
  globalThis.fetch = async (url, { signal }) => {
    assert.equal(url, "/assets/map/philippines-landmarks.geojson");
    assert(signal instanceof AbortSignal);
    fetches++;
    return { ok: true, json: async () => ({ type: "FeatureCollection", features: candidates }) };
  };
  const map = mapStub();
  const lifecycle = new AbortController();
  await addLandmarkLabels(map, lifecycle.signal);
  assert.equal(fetches, 1);
  assert.deepEqual(map.layers, nativeLayers, "Native layer colors and label definitions remain intact");
  assert.equal(map.before, "native-poi", "Native symbols get collision priority");
  assert.equal(map.supplemental.paint["text-color"], nativeLayers[0].paint["text-color"]);
  assert.equal(map.supplemental.layout["text-font"], map.layers[0].layout["text-font"]);
  assert(map.source.attribution.includes("CC BY 4.0"));
  assert(map.source.data.features.every((feature) => /^[A-Za-zñÑ0-9 ]*$/.test(feature.properties.display_name)));
  assert.deepEqual(map.supplemental.layout["text-field"], ["get", "display_name"]);
  assert.deepEqual(map.filters[0].at(-1), ["!", ["in", ["id"], ["literal", [1]]]]);
  map.handlers.get("idle")();
  map.handlers.get("moveend")();
  assert.equal(map.filters.length, 1, "Unchanged filters do not produce an idle loop");
  map.native = [];
  map.handlers.get("moveend")();
  assert.equal(map.filters.length, 2, "Camera changes restore eligible extras");
  lifecycle.abort();
  assert.equal(map.handlers.size, 0, "Lifecycle cleanup removes both listeners");

  const warnings = [];
  console.warn = (...args) => warnings.push(args);
  globalThis.fetch = async () => ({ ok: false, status: 404 });
  const unavailable = mapStub();
  await addLandmarkLabels(unavailable, new AbortController().signal);
  assert.equal(unavailable.source, null);
  assert.deepEqual(unavailable.layers, nativeLayers);
  assert.equal(warnings.length, 1, "Asset failure preserves the native map");
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ type: "FeatureCollection",
    features: [{ ...candidates[0], properties: { ...candidates[0].properties, category: "places" } }] }) });
  const invalid = mapStub();
  await addLandmarkLabels(invalid, new AbortController().signal);
  assert.equal(invalid.source, null, "Reject place or administrative label data");
  const aborted = mapStub();
  await addLandmarkLabels(aborted, AbortSignal.abort());
  assert.equal(aborted.source, null, "Do not modify a map disposed during fetch");
} finally {
  globalThis.fetch = originalFetch;
  console.warn = originalWarn;
}
console.log("PASS landmark asset, duplicate suppression, native style priority/colors, cached filters, fetch failure and cleanup");
