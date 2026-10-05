import type { components } from "./api/schema";
import type { Earthquake } from "./events";

export type EarthquakeSearch = Omit<components["schemas"]["SearchRequest"], "cursor">;
const storageKey = "quakestrike-earthquakes-v1";

function isEarthquake(value: unknown): value is Earthquake {
  if (!value || typeof value !== "object") return false;
  const row = value as Earthquake;
  return typeof row.eventId === "string" &&
    typeof row.eventTime === "string" && Number.isFinite(Date.parse(row.eventTime)) &&
    typeof row.locationDescription === "string" &&
    [row.magnitude, row.latitude, row.longitude, row.depthKm].every(Number.isFinite) &&
    (row.forecast === null || (!!row.forecast &&
      typeof row.forecast.forecastId === "string" &&
      typeof row.forecast.windowStart === "string" &&
      typeof row.forecast.windowEnd === "string" &&
      typeof row.forecast.expired === "boolean" &&
      [row.forecast.probabilityM4Plus24h, row.forecast.probabilityM5Plus24h].every(Number.isFinite)));
}

export function readEarthquakeCache(query: EarthquakeSearch): { items: Earthquake[]; fetchedAt: string } | null {
  try {
    const cached = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
    if (!cached || cached.query !== JSON.stringify(query) ||
      !Array.isArray(cached.items) || cached.items.length > 30 ||
      !cached.items.every(isEarthquake) || typeof cached.fetchedAt !== "string" ||
      !Number.isFinite(Date.parse(cached.fetchedAt))) return null;
    return { items: cached.items, fetchedAt: cached.fetchedAt };
  } catch {
    return null;
  }
}

export function writeEarthquakeCache(query: EarthquakeSearch, data: components["schemas"]["SearchResponse"]): void {
  try {
    sessionStorage.setItem(storageKey, JSON.stringify({
      query: JSON.stringify(query), items: data.items.slice(0, 30), fetchedAt: data.fetchedAt,
    }));
  } catch {
    // Unavailable storage must not prevent live results from loading.
  }
}
