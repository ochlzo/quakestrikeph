import assert from "node:assert/strict";
import { test } from "node:test";
import { scenarioStatus } from "../src/features/delivery/scenario-status.ts";

const scenario = (counts, queue_status = "enqueued") => ({ queue_status,
  counts: { pending: 0, skipped: 0, accepted: 0, delivered: 0, failed: 0, unknown: 0, ...counts } });

test("provider acceptance and uncertainty never claim delivery", () => {
  assert.equal(scenarioStatus(scenario({ accepted: 2, delivered: 1, skipped: 1 })).label, "Awaiting delivery");
  assert.equal(scenarioStatus(scenario({ unknown: 1, accepted: 1, delivered: 2 })).label, "Outcome uncertain");
});

test("new callback evidence updates the badge without changing queue status", () => {
  const item = scenario({ accepted: 1, skipped: 1 });
  assert.equal(scenarioStatus(item).label, "Awaiting delivery");
  item.counts.accepted = 0;
  item.counts.delivered = 1;
  assert.deepEqual(scenarioStatus(item), { label: "Delivered", tone: "teal" });
  item.counts.delivered = 0;
  item.counts.failed = 1;
  assert.equal(scenarioStatus(item).label, "Delivery failed");
});

test("mixed terminal outcomes preserve failure evidence", () => {
  assert.equal(scenarioStatus(scenario({ failed: 1, delivered: 1, skipped: 2 })).label, "Some deliveries failed");
});
