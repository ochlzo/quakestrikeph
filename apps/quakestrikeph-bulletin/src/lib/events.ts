import type { components } from "./api/schema";

export type Earthquake = components["schemas"]["EarthquakeSummary"];
export type Forecast = components["schemas"]["Forecast"];
export type EarthquakeDetail = components["schemas"]["EarthquakeDetail"];

export function displayTime(value: string) {
  return new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true }).format(new Date(value)) + ' (PHT)';
}

export function magnitude(value: number) { return `M${value.toFixed(1)}`; }

// Only shorten the known PHIVOLCS distance/bearing format; other descriptions stay intact.
export function locationLabel(description: string) {
  const reference = description.match(
    /^\d+(?:\.\d+)?\s+km\s+[NSEW](?:\s*\d+(?:\.\d+)?\s*°?\s*[NSEW])?\s+of\s+(.+)$/i,
  )?.[1];
  if (!reference) return description;
  const place = reference.replace(/^.+?\s+\(Municipality of ([^)]+)\)(.*)$/i, "$1$2");
  return `Near ${place}`;
}
