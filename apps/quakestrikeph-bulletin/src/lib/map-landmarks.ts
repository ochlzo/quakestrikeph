import type { Map as MapLibreMap, MapGeoJSONFeature, SymbolLayerSpecification } from "maplibre-gl";
import { cleanMapLabel } from "./map-labels.ts";

type Landmark = {
  type: "Feature";
  id: number;
  properties: { name: string; category: "landmarks"; minzoom: number };
  geometry: { type: "Point"; coordinates: [number, number] };
};
const layerId = "geonames-landmarks";

export function normalizeLabel(name: unknown): string {
  return String(name || "").normalize("NFD").replace(/\p{M}/gu, "")
    .toLowerCase().replace(/^(?:mount|mt\.?|volcano)\s+|\s+volcano$/g, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

export function duplicateLabelIds(candidates: Landmark[], nativeFeatures: Pick<MapGeoJSONFeature, "geometry" | "properties">[]): number[] {
  const names = new Map<string, number[][]>();
  for (const feature of nativeFeatures) {
    if (feature.geometry?.type !== "Point") continue;
    for (const field of ["name", "name_en", "name:en", "name:latin"]) {
      const name = normalizeLabel(feature.properties?.[field]);
      if (!name) continue;
      const positions = names.get(name) || [];
      positions.push(feature.geometry.coordinates);
      names.set(name, positions);
    }
  }
  // ponytail: nearby-name heuristic; aliases and anchors over 1 km apart need better source matching.
  return candidates.filter((feature) => {
    const [lng, lat] = feature.geometry.coordinates;
    return (names.get(normalizeLabel(feature.properties.name)) || []).some(([x, y]) => {
      const north = (lat - y) * 111320;
      const east = (lng - x) * 111320 * Math.cos(lat * Math.PI / 180);
      return Math.hypot(north, east) < 1000;
    });
  }).map((feature) => feature.id).sort((a, b) => a - b);
}

function isLandmark(value: unknown): value is Landmark {
  const feature = value as Partial<Landmark> | null;
  const coordinates = feature?.geometry?.coordinates;
  return feature?.type === "Feature" && Number.isSafeInteger(feature.id)
    && feature.geometry?.type === "Point" && Array.isArray(coordinates)
    && coordinates.length === 2 && coordinates.every(Number.isFinite)
    && Math.abs(coordinates[0]) <= 180 && Math.abs(coordinates[1]) <= 90
    && feature.properties?.category === "landmarks"
    && typeof feature.properties.name === "string" && !!feature.properties.name.trim()
    && Number.isFinite(feature.properties.minzoom);
}

export async function addLandmarkLabels(map: MapLibreMap, signal: AbortSignal): Promise<void> {
  try {
    const response = await fetch("/assets/map/philippines-landmarks.geojson", { signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json() as { type?: string; features?: unknown[] };
    if (signal.aborted) return;
    if (data?.type !== "FeatureCollection" || !Array.isArray(data.features)
      || !data.features.length || !data.features.every(isLandmark)) {
      throw new Error("Invalid mountain and landmark dataset");
    }
    const features = data.features;
    const symbols = map.getStyle().layers.filter(
      (layer): layer is SymbolLayerSpecification => layer.type === "symbol",
    );
    const nativeLayers = symbols.filter((layer) => layer.layout?.["text-field"]).map((layer) => layer.id);
    // Reuse native POI text colors/fonts without modifying any basemap layer.
    const label = symbols.find((layer) => layer["source-layer"] === "poi" && layer.layout?.["text-field"])
      || symbols.find((layer) => layer.layout?.["text-field"]);
    map.addSource(layerId, {
      type: "geojson",
      data: { type: "FeatureCollection", features: features.map((feature) => ({
        ...feature, properties: { ...feature.properties, display_name: cleanMapLabel(feature.properties.name) },
      })) },
    });
    map.addLayer({
      id: layerId,
      type: "symbol",
      source: layerId,
      minzoom: 5,
      filter: [">=", ["zoom"], ["get", "minzoom"]],
      layout: {
        "text-field": ["get", "display_name"],
        "text-font": label?.layout?.["text-font"],
        "text-size": ["interpolate", ["linear"], ["zoom"], 5, 11, 12, 13],
        "text-max-width": 9,
        "text-padding": 5,
        "text-variable-anchor": ["center", "top", "bottom", "left", "right"],
        "text-pitch-alignment": "viewport",
        "text-rotation-alignment": "viewport",
        "symbol-sort-key": ["get", "minzoom"],
      },
      paint: {
        "text-color": label?.paint?.["text-color"],
        "text-halo-color": label?.paint?.["text-halo-color"],
        "text-halo-width": label?.paint?.["text-halo-width"],
        "text-halo-blur": label?.paint?.["text-halo-blur"],
      },
    }, symbols[0]?.id); // Native symbols placed later have higher collision priority.

    let previousIds = "";
    const updateGaps = () => {
      if (signal.aborted) return;
      const bounds = map.getBounds();
      const candidates = features.filter((feature) => feature.properties.minzoom <= map.getZoom()
        && bounds.contains(feature.geometry.coordinates));
      const ids = duplicateLabelIds(candidates,
        nativeLayers.length ? map.queryRenderedFeatures({ layers: nativeLayers }) : []);
      const key = JSON.stringify(ids);
      if (key === previousIds) return; // An unchanged filter would trigger idle repeatedly.
      previousIds = key;
      map.setFilter(layerId, ["all", [">=", ["zoom"], ["get", "minzoom"]],
        ["!", ["in", ["id"], ["literal", ids]]]]);
    };
    map.on("moveend", updateGaps);
    map.on("idle", updateGaps);
    signal.addEventListener("abort", () => {
      map.off("moveend", updateGaps);
      map.off("idle", updateGaps);
    }, { once: true });
    updateGaps();
  } catch (error) {
    if (signal.aborted) return;
    if (map.getLayer(layerId)) map.removeLayer(layerId);
    if (map.getSource(layerId)) map.removeSource(layerId);
    console.warn("Supplemental map labels unavailable; native labels remain active.", error);
  }
}
