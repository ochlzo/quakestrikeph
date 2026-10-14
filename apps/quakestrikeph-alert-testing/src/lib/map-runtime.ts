import workerUrl from "./map-worker.ts?worker&url";

let runtime: Promise<typeof import("maplibre-gl")> | undefined;
export function loadMapRuntime() {
  runtime ??= import("maplibre-gl").then(lib => {
    lib.setWorkerUrl(workerUrl);
    return lib;
  }).catch(error => { runtime = undefined; throw error; });
  return runtime;
}
