import assert from "node:assert/strict";
import { test } from "node:test";
import { likelihoodLevel } from "../src/lib/events.ts";

test("forecast likelihood uses raw probability at both cutoffs", () => {
  for (const [probability, expected] of [
    [0, "Low likelihood"], [0.08, "Low likelihood"], [0.2999, "Low likelihood"],
    [0.3, "Medium likelihood"], [0.6999, "Medium likelihood"],
    [0.7, "High likelihood"], [1, "High likelihood"],
  ]) {
    assert.equal(likelihoodLevel(probability), expected);
  }
});
