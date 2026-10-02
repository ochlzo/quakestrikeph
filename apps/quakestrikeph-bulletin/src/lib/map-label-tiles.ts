import { VectorTile } from "@mapbox/vector-tile";
import { fromVectorTileJs, type VectorTileLike } from "@maplibre/vt-pbf";
import { PbfReader } from "pbf";
import type { AddProtocolAction } from "maplibre-gl";
import { cleanMapLabel, englishMapLabel, labelProtocol } from "./map-labels.ts";
import { cacheLabelTile, readLabelTile } from "./map-label-cache.ts";
export { labelProtocol, transformLabelRequest } from "./map-labels.ts";

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
  controller.signal.throwIfAborted();
  const url = request.url.slice(`${labelProtocol}://`.length);
  const cached = await readLabelTile(url);
  controller.signal.throwIfAborted();
  if (cached) {
    const data = await cached.arrayBuffer();
    controller.signal.throwIfAborted();
    return { data, cacheControl: cached.headers.get("Cache-Control") || undefined,
      expires: cached.headers.get("Expires") || undefined };
  }
  const response = await fetch(url, {
    signal: controller.signal,
    headers: request.headers,
    credentials: request.credentials,
  });
  if (!response.ok) throw new Error(`Map label tile HTTP ${response.status}`);
  const bytes = await response.arrayBuffer();
  controller.signal.throwIfAborted();
  const data = cleanLabelTile(bytes);
  const headers = new Headers({ "Content-Type": "application/x-protobuf" });
  for (const field of ["Cache-Control", "Expires"]) {
    const value = response.headers.get(field);
    if (value) headers.set(field, value);
  }
  await cacheLabelTile(url, data, headers);
  controller.signal.throwIfAborted();
  return {
    data,
    cacheControl: response.headers.get("Cache-Control") || undefined,
    expires: response.headers.get("Expires") || undefined,
  };
};
