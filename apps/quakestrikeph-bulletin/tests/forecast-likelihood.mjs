// node --experimental-strip-types tests/forecast-likelihood.mjs
import assert from "node:assert/strict";
import { likelihoodLevel } from "../src/lib/events.ts";

for (const [probability, expected] of [
  [0, "Low likelihood"], [0.08, "Low likelihood"], [0.2999, "Low likelihood"],
  [0.3, "Moderate likelihood"], [0.6999, "Moderate likelihood"],
  [0.7, "High likelihood"], [1, "High likelihood"],
]) {
  assert.equal(likelihoodLevel(probability), expected);
}
console.log("Forecast likelihood thresholds passed.");
