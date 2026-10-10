import type { Earthquake, Forecast } from '../../domain/information.js';
import { forecastExpired } from '../../domain/information.js';

function forecastSummary(forecast: Forecast | null, now: Date) {
  if (!forecast) return null;
  return {
    forecastId: forecast.forecastId,
    windowStart: forecast.windowStart,
    windowEnd: forecast.windowEnd,
    expired: forecastExpired(forecast, now),
    probabilityM4Plus24h: forecast.probabilityM4Plus24h,
    probabilityM5Plus24h: forecast.probabilityM5Plus24h,
  };
}

export function listItem(earthquake: Earthquake, now: Date) {
  return {
    eventId: earthquake.eventId,
    eventTime: earthquake.eventTime,
    magnitude: earthquake.magnitude,
    latitude: earthquake.latitude,
    longitude: earthquake.longitude,
    depthKm: earthquake.depthKm,
    locationDescription: earthquake.locationDescription,
    forecast: forecastSummary(earthquake.forecast, now),
  };
}

export function detail(earthquake: Earthquake, now: Date) {
  return {
    ...listItem(earthquake, now),
    eventRevisionId: earthquake.eventRevisionId,
    origin: earthquake.origin,
    source: { provider: 'PHIVOLCS', url: earthquake.sourceUrl },
    forecast: earthquake.forecast ? { ...earthquake.forecast, expired: forecastExpired(earthquake.forecast, now) } : null,
    forecastAvailability: earthquake.forecastAvailability,
  };
}
