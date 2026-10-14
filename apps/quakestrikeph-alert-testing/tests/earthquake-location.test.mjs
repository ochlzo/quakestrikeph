import assert from "node:assert/strict";
import { test } from "node:test";
import { initialInputs } from "../src/features/workspace/workspace-memory.ts";
import { earthquakePoint, earthquakeLocationLabel, matchingPlaces, applyEarthquakeLocation } from "../src/features/scenarios/earthquake-location.ts";

const places = [
  ["Surigao City", "Surigao del Norte", 9.79, 125.49, "Surigao"],
  ["Makati City", "Metro Manila", 14.55, 121.03, "National Capital Region"],
];

test("location search handles accents, aliases, and the selected display label", () => {
  assert.equal(matchingPlaces(places, "MAKÁTI")[0].index, 1);
  assert.equal(matchingPlaces(places, "National Capital")[0].index, 1);
  assert.equal(matchingPlaces(places, "Makati City, Metro Manila")[0].index, 1);
  assert.deepEqual(matchingPlaces(places, "m"), []);
});

test("map and search share exact coordinates and a corresponding description", () => {
  const inputs = initialInputs(), point = [14.55, 121.03];
  const result = applyEarthquakeLocation(inputs, point, places);
  assert.deepEqual(earthquakePoint(result), point);
  assert.equal(result.location, "Makati City, Metro Manila");
  for (const key of Object.keys(inputs)) if (!["latitude", "longitude", "location"].includes(key)) assert.equal(result[key], inputs[key]);
  assert.equal(earthquakeLocationLabel([14.56, 121.04], places), "Pin near Makati City, Metro Manila");
  assert.equal(earthquakeLocationLabel([-30, -120], places), "30.00000° S, 120.00000° W");
});

test("empty or invalid coordinate edits do not become a map pin", () => {
  for (const [latitude, longitude] of [["", "125"], [" ", "125"], ["91", "125"], ["9", "181"], ["NaN", "125"]]) {
    assert.equal(earthquakePoint({ latitude, longitude }), null);
  }
});
