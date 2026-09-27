export interface MagnitudeRange {
  from?: number;
  below?: number;
}

export interface SearchCursor {
  eventTime: string;
  eventId: string;
}

export interface EarthquakeSearch {
  magnitudeRanges: MagnitudeRange[];
  dateFrom?: string;
  dateTo?: string;
  location?: string;
  limit: number;
  cursor?: SearchCursor;
}

export interface Forecast {
  forecastId: string;
  modelReleaseId: string;
  windowStart: string;
  windowEnd: string;
  probabilityM1Plus24h: number;
  expectedM1PlusCount24h: number;
  probabilityM4Plus24h: number;
  probabilityM5Plus24h: number;
  activityRadiusMedianKm24h: number | null;
  maximumMagnitudeQ05_24h: number | null;
  maximumMagnitudeQ50_24h: number | null;
  maximumMagnitudeQ95_24h: number | null;
}

export interface Earthquake {
  eventId: string;
  eventRevisionId: string;
  eventTime: string;
  magnitude: number;
  latitude: number;
  longitude: number;
  depthKm: number;
  locationDescription: string;
  origin: string | null;
  sourceUrl: string;
  forecast: Forecast | null;
}

export function forecastExpired(forecast: Forecast, now: Date): boolean {
  return new Date(forecast.windowEnd).getTime() <= now.getTime();
}

export function validMagnitudeRange(range: MagnitudeRange): boolean {
  return (
    (range.from !== undefined || range.below !== undefined) &&
    (range.from === undefined || Number.isFinite(range.from)) &&
    (range.below === undefined || Number.isFinite(range.below)) &&
    (range.from === undefined || range.below === undefined || range.from < range.below)
  );
}
