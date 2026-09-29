export type Earthquake = {
  eventId: string;
  eventTime: string;
  magnitude: number;
  latitude: number;
  longitude: number;
  depthKm: number | null;
  locationDescription: string;
  source?: { provider: string; url: string };
};

export type Forecast = {
  forecastId: string;
  windowStart: string;
  windowEnd: string;
  expired: boolean;
  probabilityM1Plus24h: number;
  probabilityM4Plus24h: number;
  probabilityM5Plus24h: number;
  activityRadiusMedianKm24h: number | null;
};

export type EarthquakeDetail = Earthquake & { forecast: Forecast | null };

export function displayTime(value: string) {
  return new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true }).format(new Date(value)) + ' (PHT)';
}

export function magnitude(value: number) { return `M${value.toFixed(1)}`; }
