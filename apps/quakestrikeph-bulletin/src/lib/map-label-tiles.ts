import { VectorTile } from "@mapbox/vector-tile";
import { fromVectorTileJs, type VectorTileLike } from "@maplibre/vt-pbf";
import { PbfReader } from "pbf";
import type { AddProtocolAction, RequestTransformFunction } from "maplibre-gl";
import { cleanMapLabel, englishMapLabel } from "./map-labels.ts";

export const labelProtocol = "quakestrike-labels";

export const transformLabelRequest: RequestTransformFunction = (url, type) => {
  if (type === "Tile" && url.startsWith("https://tiles.openfreemap.org/planet/")
    && new URL(url).pathname.endsWith(".pbf")) {
    return { url: `${labelProtocol}://${url}` };
  }
  return undefined;
};

export function cleanLabelTile(data: ArrayBuffer): ArrayBuffer {
  const tile = new VectorTile(new PbfReader(data));
  const layers: VectorTileLike["layers"] = {};
  for (const [name, layer] of Object.entries(tile.layers)) {
    layers[name] = {
      name: layer.name, version: layer.version, extent: layer.extent, length: layer.length,
      feature(index) {
        const feature = layer.feature(index);
        if (["name:en", "name_en", "name:latin", "name"].some((field) => field in feature.properties)) {
          feature.properties.qs_name = englishMapLabel(feature.properties);
        }
        if ("ref" in feature.properties) feature.properties.qs_ref = cleanMapLabel(feature.properties.ref);
        return feature;
      },
    };
  }
  return new Uint8Array(fromVectorTileJs({ layers })).buffer;
}

export const loadLabelTile: AddProtocolAction = async (request, controller) => {
  const response = await fetch(request.url.slice(`${labelProtocol}://`.length), {
    signal: controller.signal,
    headers: request.headers,
    credentials: request.credentials,
  });
  if (!response.ok) throw new Error(`Map label tile HTTP ${response.status}`);
  const data = cleanLabelTile(await response.arrayBuffer());
  return {
    data,
    cacheControl: response.headers.get("Cache-Control") || undefined,
    expires: response.headers.get("Expires") || undefined,
  };
};
