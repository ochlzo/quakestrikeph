export type ScenarioInputs = Record<
  "location" | "magnitude" | "depth" | "latitude" | "longitude" | "time" |
  "p1" | "p4" | "p5" | "count" | "radius" | "q05" | "q50" | "q95" |
  "local" | "background" | "spread" | "spillover" | "preset", string>;

export type PreparedScenario = Readonly<{
  version: 1;
  session_id: string;
  event_id: string;
  prepared_at_ms: number;
  expires_at_ms: number;
  event: Readonly<{ location: string; magnitude: number; depth_km: number; latitude: number; longitude: number; event_time_ms: number }>;
  forecast: Readonly<{
    window_start_ms: number; window_end_ms: number; p1: number; p4: number; p5: number;
    count: number; radius_km: number; quantiles: readonly [number, number, number] | null;
  }>;
  replay: Readonly<{ local: number; background: number; spread: number; spillover: number }>;
  observations: readonly Readonly<{
    event_id: string; event_time_ms: number; latitude: number; longitude: number;
    magnitude: number; depth_km: number; location_description: string;
    kind: "inside" | "spillover" | "background";
    distance_km: number; bearing_radians: number;
  }>[];
}>;
