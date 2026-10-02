import "maplibre-gl/dist/maplibre-gl-worker.mjs";
import type { AddProtocolAction } from "maplibre-gl";
import { labelProtocol } from "./map-labels";
import { loadLabelTile } from "./map-label-tiles";

// MapLibre installs this API on its worker scope when the module above initializes.
const workerScope = self as unknown as {
  addProtocol: (name: string, handler: AddProtocolAction) => void;
};
workerScope.addProtocol(labelProtocol, loadLabelTile);
