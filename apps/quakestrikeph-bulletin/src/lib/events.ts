import type { components } from "./api/schema";

export type Earthquake = components["schemas"]["EarthquakeSummary"];
export type Forecast = components["schemas"]["Forecast"];
export type EarthquakeDetail = components["schemas"]["EarthquakeDetail"];

// Display categories use probability, not earthquake severity.
export function likelihoodLevel(probability: number) {
  return probability < 0.3 ? "Low likelihood" : probability < 0.7 ? "Moderate likelihood" : "High likelihood";
}

export function displayTime(value: string) {
  return new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true }).format(new Date(value)) + ' (PHT)';
}

export function magnitude(value: number) { return `M${value.toFixed(1)}`; }

// Preserve source wording; remove padding only from the leading kilometre distance.
export function locationLabel(description: string) {
  return description.replace(/^0+(?=\d+(?:\.\d+)?\s+km\b)/i, "");
}
