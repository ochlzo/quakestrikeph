import type { Earthquake } from './information.js';

export interface SyntheticScenario {
  event: Earthquake;
  observations: Earthquake[];
  expiresAtMs: number;
}

type RecordValue = Record<string, unknown>;
function object(value: unknown): RecordValue {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid record');
  return value as RecordValue;
}
function number(value: unknown, min: number, max: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) throw new Error('Invalid number');
  return value;
}
function time(value: unknown): number {
  const result = number(value, -8.64e15, 8.64e15);
  if (!Number.isSafeInteger(result)) throw new Error('Invalid timestamp');
  return result;
}
function text(value: unknown): string {
  if (typeof value !== 'string' || !value.trim() || value.length > 300) throw new Error('Invalid text');
  return value;
}
function uuid(value: unknown): string {
  const result = text(value);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(result)) throw new Error('Invalid identity');
  return result;
}

// Explicit projection prevents private fields added by the producer from reaching public responses.
export function projectSubmittedScenario(raw: unknown, sessionId: string, deadline: number, eventId: string): SyntheticScenario | null {
  const record = object(raw);
  if (record.submitted !== true && record.preview !== true) return null;
  if (record.version !== 1) throw new Error('Unsupported submitted record');
  const scenario = object(record.scenario);
  if (scenario.version !== 1 || uuid(scenario.session_id) !== sessionId || uuid(scenario.event_id) !== eventId ||
      time(scenario.expires_at_ms) !== deadline) throw new Error('Invalid ownership');
  const prepared = time(scenario.prepared_at_ms), submitted = time(record.submitted === true ? record.submitted_at_ms : record.saved_at_ms);
  if (prepared > submitted || submitted >= deadline) throw new Error('Invalid submission time');
  const anchor = object(scenario.event), forecast = object(scenario.forecast);
  const start = time(forecast.window_start_ms), end = time(forecast.window_end_ms);
  if (start !== time(anchor.event_time_ms) || end - start !== 86400000) throw new Error('Invalid window');
  const p1 = number(forecast.p1, 0, 1), p4 = number(forecast.p4, 0, 1), p5 = number(forecast.p5, 0, 1);
  if (p5 > p4 || p4 > p1) throw new Error('Invalid probabilities');
  let quantiles: number[] | null = null;
  if (forecast.quantiles !== null) {
    if (!Array.isArray(forecast.quantiles) || forecast.quantiles.length !== 3) throw new Error('Invalid quantiles');
    quantiles = forecast.quantiles.map(value => number(value, -Infinity, Infinity));
    if (quantiles[0]! > quantiles[1]! || quantiles[1]! > quantiles[2]!) throw new Error('Invalid quantile order');
  }
  const event: Earthquake = {
    eventId, eventRevisionId: uuid(record.event_revision_id), eventTime: new Date(start).toISOString(),
    magnitude: number(anchor.magnitude, 1, 10), depthKm: number(anchor.depth_km, 0, 700),
    latitude: number(anchor.latitude, -90, 90), longitude: number(anchor.longitude, -180, 180),
    locationDescription: text(anchor.location), origin: null, sourceUrl: 'https://earthquake.phivolcs.dost.gov.ph/',
    forecastAvailability: { status: 'available', reason: null },
    forecast: {
      forecastId: uuid(record.forecast_id), modelReleaseId: uuid(record.model_release_id),
      windowStart: new Date(start).toISOString(), windowEnd: new Date(end).toISOString(),
      probabilityM1Plus24h: p1, probabilityM4Plus24h: p4, probabilityM5Plus24h: p5,
      expectedM1PlusCount24h: number(forecast.count, 0, Infinity),
      activityRadiusMedianKm24h: number(forecast.radius_km, Number.MIN_VALUE, Math.PI * 6371.0088 - 0.001),
      maximumMagnitudeQ05_24h: quantiles?.[0] ?? null, maximumMagnitudeQ50_24h: quantiles?.[1] ?? null,
      maximumMagnitudeQ95_24h: quantiles?.[2] ?? null,
    },
  };
  if (!Array.isArray(scenario.observations) || scenario.observations.length > 200) throw new Error('Invalid observations');
  const identities = new Set([eventId]);
  const observations = scenario.observations.map(value => {
    const item = object(value), id = uuid(item.event_id), timestamp = time(item.event_time_ms);
    if (identities.has(id) || timestamp < start || timestamp > end) throw new Error('Invalid observation identity or time');
    identities.add(id);
    return {
      eventId: id, eventRevisionId: id, eventTime: new Date(timestamp).toISOString(),
      magnitude: number(item.magnitude, 0, 10), depthKm: number(item.depth_km, 0, 700),
      latitude: number(item.latitude, -90, 90), longitude: number(item.longitude, -180, 180),
      locationDescription: text(item.location_description), origin: null, sourceUrl: event.sourceUrl,
      forecast: null, forecastAvailability: { status: 'unavailable', reason: 'unknown' } as const,
    };
  });
  return { event, observations, expiresAtMs: deadline };
}
