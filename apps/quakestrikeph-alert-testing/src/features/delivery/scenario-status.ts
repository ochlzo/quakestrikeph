import type { ScenarioResult } from "../../../../../packages/contracts/alert-testing/delivery-v1";

export function scenarioStatus(item: ScenarioResult) {
  const counts = item.counts;
  const total = Object.values(counts).reduce((sum, count) => sum + count, 0);
  if (!total || counts.pending === total) {
    return { label: item.queue_status === "enqueued" ? "Queued" : "Queue pending", tone: "amber" };
  }
  if (counts.pending) return { label: "Processing", tone: "amber" };
  if (counts.unknown) return { label: "Outcome uncertain", tone: "amber" };
  if (counts.accepted) return { label: "Awaiting delivery", tone: "amber" };
  if (counts.failed) return { label: counts.delivered ? "Some deliveries failed" : "Delivery failed", tone: "red" };
  if (counts.delivered) return { label: "Delivered", tone: "teal" };
  return { label: "All skipped", tone: "neutral" };
}
