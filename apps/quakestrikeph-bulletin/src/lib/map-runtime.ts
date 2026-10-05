import workerUrl from "./map-worker.ts?worker&url";

let runtime: Promise<typeof import("maplibre-gl")> | undefined;

export function loadMapRuntime(): Promise<typeof import("maplibre-gl")> {
  runtime ??= import("maplibre-gl").then((maplibre) => {
    maplibre.setWorkerUrl(workerUrl);
    maplibre.prewarm();
    return maplibre;
  }).catch((error) => {
    runtime = undefined;
    throw error;
  });
  return runtime;
}
