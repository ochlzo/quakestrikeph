import type { StyleSpecification } from "maplibre-gl";

export function cleanMapLabel(value: unknown): string {
  return String(value ?? "").normalize("NFKD")
    .replace(/[nN]\u0303/g, (letter) => letter.normalize("NFC"))
    .replace(/[^A-Za-zñÑ0-9\s]/g, "").replace(/\s+/g, " ").trim();
}

export function englishMapLabel(properties: Record<string, unknown>): string {
  for (const field of ["name:en", "name_en", "name:latin", "name"]) {
    const label = cleanMapLabel(properties[field]);
    if (label) return label;
  }
  return "";
}

export function cleanMapStyle(style: StyleSpecification): StyleSpecification {
  return { ...style, layers: style.layers.map((layer) => {
    if (layer.type !== "symbol" || layer.source !== "openmaptiles"
      || !layer.layout?.["text-field"]) return layer;
    return { ...layer, layout: { ...layer.layout,
      "text-field": ["coalesce", ["get", layer.id.includes("shield") ? "qs_ref" : "qs_name"], ""],
    } };
  }) };
}
