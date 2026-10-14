import type { Inputs } from "../workspace/workspace-memory.ts";

// Coordinate descriptions keep synthetic locations consistent without geocoding.
export function randomizeEarthquake(inputs: Inputs, now = Date.now(), random = Math.random): Inputs {
  const latitude = (5 + random() * 15).toFixed(2);
  const longitude = (118 + random() * 9).toFixed(2);
  const magnitude = (3 + random() * 4).toFixed(1);
  const depth = String(5 + Math.floor(random() * 96));
  const eventTime = now - Math.floor(random() * 60) * 60000;
  const time = new Date(eventTime + 8 * 3600000).toISOString().slice(0, 16);
  return { ...inputs, location: `${latitude}° N, ${longitude}° E`, latitude, longitude,
    magnitude, depth, time };
}
