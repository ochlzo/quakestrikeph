import type { components } from "./api/schema";

export type Earthquake = components["schemas"]["EarthquakeSummary"];
export type Forecast = components["schemas"]["Forecast"];
export type EarthquakeDetail = components["schemas"]["EarthquakeDetail"];

// Display categories use probability, not earthquake severity.
export function likelihoodLevel(probability: number) {
  return probability < 0.3 ? "Low likelihood" : probability < 0.7 ? "Moderate likelihood" : "High likelihood";
}

const philippineTimeOptions = {
  timeZone: "Asia/Manila", year: "numeric", month: "short", day: "numeric",
  hour: "2-digit", minute: "2-digit", hour12: true,
} as const;
const philippineTime = new Intl.DateTimeFormat("en-PH", philippineTimeOptions);
const philippineTimeWithSeconds = new Intl.DateTimeFormat("en-PH", {
  ...philippineTimeOptions, second: "2-digit",
});

export function displayTime(value: string) {
  return philippineTime.format(new Date(value)) + " (PHT)";
}

export function displayTimeWithSeconds(value: string) {
  return philippineTimeWithSeconds.format(new Date(value)) + " (PHT)";
}

export function magnitude(value: number) { return `M${value.toFixed(1)}`; }

export function occurrenceRelativeTo(eventTime: string, triggerTime: string) {
  const difference = Date.parse(eventTime) - Date.parse(triggerTime);
  if (difference === 0) return "Occurred at the same time as the trigger earthquake";
  const minutes = Math.abs(difference) / 60000;
  const unit = minutes < 60 ? "minute" : "hour";
  const amount = unit === "minute"
    ? Math.round(minutes)
    : Math.round((minutes / 60) * 10) / 10;
  const duration = minutes < 1
    ? "less than 1 minute"
    : `${amount} ${unit}${amount === 1 ? "" : "s"}`;
  return `Occurred ${duration} ${difference < 0 ? "before" : "after"} the trigger earthquake`;
}

// Preserve source wording; remove padding only from the leading kilometre distance.
export function locationLabel(description: string) {
  return description.replace(/^0+(?=\d+(?:\.\d+)?\s+km\b)/i, "");
}
