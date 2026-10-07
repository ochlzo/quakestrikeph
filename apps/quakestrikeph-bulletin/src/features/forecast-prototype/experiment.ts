import fixture from "./fixtures/sample-catalog.json";
import type { ClusteringReply, ClusteringRequest } from "./clustering.worker";

/** One worker per run makes cancellation and failure independent of later runs. */
function run(request: ClusteringRequest): Promise<ClusteringReply> {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("./clustering.worker.ts", import.meta.url), { type: "module" });
    const timer = setTimeout(() => { worker.terminate(); reject(new Error("Sample computation exceeded 30 seconds.")); }, 30000);
    const finish = () => { clearTimeout(timer); worker.terminate(); };
    worker.onmessage = ({ data }: MessageEvent<ClusteringReply>) => { finish(); resolve(data); };
    worker.onerror = event => { finish(); reject(new Error(event.message)); };
    worker.postMessage(request);
  });
}

// The isolated development harness exposes this function for native-reference browser comparisons.
(window as unknown as { forecastClusteringExperiment: { run: typeof run } }).forecastClusteringExperiment = { run };
const select = document.querySelector<HTMLSelectElement>("#scenario")!;
const button = document.querySelector<HTMLButtonElement>("#run")!;
const status = document.querySelector<HTMLElement>("#status")!;
const windowLabel = document.querySelector<HTMLElement>("#window")!;
const table = document.querySelector<HTMLTableSectionElement>("#assignments")!;
for (const scenario of fixture.scenarios) select.add(new Option(scenario.id, scenario.id));
const describe = () => {
  document.querySelector<HTMLElement>("#description")!.textContent = fixture.scenarios[select.selectedIndex].description;
};
select.addEventListener("change", () => {
  describe(); table.replaceChildren(); windowLabel.textContent = ""; status.textContent = "Run the selected sample case.";
});
describe();
button.addEventListener("click", async () => {
  button.disabled = select.disabled = true;
  status.textContent = "Calculating sample relationships…";
  table.replaceChildren(); windowLabel.textContent = "";
  try {
    const scenario = fixture.scenarios[select.selectedIndex];
    const reply = await run({ requestId: scenario.id, anchorId: scenario.anchorId,
      events: scenario.events as ClusteringRequest["events"], settings: scenario.settings ?? fixture.settings });
    if (!reply.ok) throw new Error(reply.error);
    status.textContent = `${reply.result.assignments.length} included sample events. Worker computation: ${reply.computationMs.toFixed(2)} ms. Excludes loading and worker startup.`;
    windowLabel.textContent = `Selected earthquake: ${scenario.anchorId}. Possibly related events in its 24-hour window: ${reply.windowEventIds.length}.`;
    const selected = new Set(reply.windowEventIds);
    for (const assignment of reply.result.assignments) {
      const row = document.createElement("tr");
      for (const value of [assignment.event.eventId, assignment.parentId ?? "No eligible earlier event",
        assignment.linkType, String(assignment.groupId), selected.has(assignment.event.eventId) ? "Included" : "Excluded"]) {
        const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
      }
      table.append(row);
    }
  } catch (error) { status.textContent = error instanceof Error ? error.message : String(error); }
  finally { button.disabled = select.disabled = false; }
});
