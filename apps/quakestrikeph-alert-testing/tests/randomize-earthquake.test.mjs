import assert from "node:assert/strict";
import { test } from "node:test";
import { randomizeEarthquake } from "../src/features/scenarios/randomize-earthquake.ts";
import { initialInputs, WorkspaceMemory } from "../src/features/workspace/workspace-memory.ts";

test("earthquake randomization keeps forecast and replay settings and produces matching coordinates", () => {
  const inputs = initialInputs(), now = Date.parse("2026-10-14T07:00:00Z");
  const result = randomizeEarthquake(inputs, now, () => 0.5);
  assert.equal(result.location, `${result.latitude}° N, ${result.longitude}° E`);
  assert.equal(result.time, "2026-10-14T14:30");
  assert.equal(result.magnitude, "5.0");
  assert.equal(result.depth, "53");
  const changed = new Set(["location", "latitude", "longitude", "magnitude", "depth", "time"]);
  for (const field of Object.keys(inputs)) if (!changed.has(field)) assert.equal(result[field], inputs[field]);
  assert.notEqual(result, inputs);
});

test("randomization invalidates preparation and preserves tester selection", async () => {
  const memory = new WorkspaceMemory(), now = Date.now();
  memory.accept({ status: "active", session_id: "session", server_time_ms: now, expires_at_ms: now + 14400000 });
  memory.edit({ ...memory.state.draft, selected: ["tester"] });
  await memory.prepare(async () => ({ session_id: "session", event_id: "old" }));
  memory.edit({ inputs: randomizeEarthquake(memory.state.draft.inputs, now, () => 0.5), selected: memory.state.draft.selected });
  assert.deepEqual(memory.state.draft.selected, ["tester"]);
  assert.equal(memory.state.prepared, null);
});
