import { clusterCatalog, windowEvents } from "./clustering";
import type { CatalogEvent, ClusteringResult, ClusteringSettings } from "./clustering";

export interface ClusteringRequest {
  requestId: string;
  events: CatalogEvent[];
  settings: ClusteringSettings;
  anchorId: string;
}

export type ClusteringReply = {
  requestId: string;
  ok: true;
  result: ClusteringResult;
  windowEventIds: string[];
  computationMs: number;
} | { requestId: string; ok: false; error: string };

// Keep worker typing local: Astro's project includes DOM declarations rather than the WebWorker library.
const scope = globalThis as unknown as {
  onmessage: ((event: MessageEvent<ClusteringRequest>) => void) | null;
  postMessage: (message: ClusteringReply) => void;
};

scope.onmessage = ({ data }) => {
  try {
    const started = performance.now();
    const result = clusterCatalog(data.events, data.settings);
    const windowEventIds = windowEvents(result, data.anchorId).map(row => row.event.eventId);
    scope.postMessage({ requestId: data.requestId, ok: true, result, windowEventIds,
      computationMs: performance.now() - started });
  } catch (error) {
    scope.postMessage({ requestId: data.requestId, ok: false,
      error: error instanceof Error ? error.message : String(error) });
  }
};
