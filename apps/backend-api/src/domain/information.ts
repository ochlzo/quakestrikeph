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

export interface ForecastAvailability {
  status: 'available' | 'processing' | 'failed' | 'unavailable';
  reason: 'insufficient_history' | 'below_minimum_magnitude' | 'model_unavailable' | 'unknown' | null;
}

export function forecastAvailability(
  forecast: Forecast | null, predictionStatus: string | null, skipReason: string | null,
): ForecastAvailability {
  // A recovered forecast or active job takes priority over an immutable skip decision.
  if (forecast) return { status: 'available', reason: null };
  if (predictionStatus === 'pending' || predictionStatus === 'running' || predictionStatus === 'retry_wait') {
    return { status: 'processing', reason: null };
  }
  if (predictionStatus === 'failed') return { status: 'failed', reason: null };
  if (predictionStatus) return { status: 'unavailable', reason: 'unknown' };
  switch (skipReason) {
    case 'history_coverage_unavailable':
    case 'incomplete_feature_history':
    case 'history_starts_after_required_window':
    case 'history_ends_before_anchor':
      return { status: 'unavailable', reason: 'insufficient_history' };
    case 'magnitude_below_m1':
      return { status: 'unavailable', reason: 'below_minimum_magnitude' };
    case 'model_release_unavailable':
      return { status: 'unavailable', reason: 'model_unavailable' };
    default:
      return { status: 'unavailable', reason: 'unknown' };
  }
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
  forecastAvailability: ForecastAvailability;
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
