import type { Inputs } from "../workspace/workspace-memory.ts";

export type Place = [string, string, number, number, string];
export type Point = [number, number];
const normalize = (text: string) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
  .toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();

export function earthquakePoint(inputs: Pick<Inputs, "latitude" | "longitude">): Point | null {
  if (!inputs.latitude.trim() || !inputs.longitude.trim()) return null;
  const latitude = Number(inputs.latitude), longitude = Number(inputs.longitude);
  return Number.isFinite(latitude) && Number.isFinite(longitude) && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180
    ? [latitude, longitude] : null;
}

export function matchingPlaces(list: Place[], query: string) {
  const text = normalize(query.trim()), terms = text.split(/\s+/);
  if (text.length < 2) return [];
  const rank = (place: Place) => normalize(place[0]) === text ? 0 : normalize(place[0]).startsWith(text) ? 1 : 2;
  return list.map((place, index) => ({ place, index }))
    .filter(({ place }) => terms.every(term => normalize(`${place[0]} ${place[1]} ${place[4]}`).includes(term)))
    .sort((left, right) => rank(left.place) - rank(right.place)).slice(0, 20);
}

export function earthquakeLocationLabel(point: Point, list: Place[]) {
  let closest: Place | undefined, distance = Infinity;
  for (const place of list) {
    const candidate = (place[2] - point[0]) ** 2 + ((place[3] - point[1]) * Math.cos(point[0] * Math.PI / 180)) ** 2;
    if (candidate < distance) { closest = place; distance = candidate; }
  }
  return closest && distance <= 1 ? `${distance > 0.000001 ? "Pin near " : ""}${closest[0]}, ${closest[1]}`
    : `${Math.abs(point[0]).toFixed(5)}° ${point[0] >= 0 ? "N" : "S"}, ${Math.abs(point[1]).toFixed(5)}° ${point[1] >= 0 ? "E" : "W"}`;
}

export function applyEarthquakeLocation(inputs: Inputs, point: Point, list: Place[], label?: string): Inputs {
  return { ...inputs, latitude: point[0].toFixed(5), longitude: point[1].toFixed(5),
    location: label ?? earthquakeLocationLabel(point, list) };
}
