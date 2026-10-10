import type { Pool, QueryResultRow } from 'pg';
import type { Earthquake, EarthquakeSearch, Forecast } from '../../domain/information.js';
import { forecastAvailability } from '../../domain/information.js';
import type { EarthquakeReader } from '../../ports/earthquakeReader.js';
import { DataUnavailable } from '../../application/information/errors.js';

interface EarthquakeRow extends QueryResultRow {
  eventId: string;
  eventRevisionId: string;
  eventTime: Date;
  magnitude: number;
  latitude: number;
  longitude: number;
  depthKm: number;
  locationDescription: string;
  origin: string | null;
  sourceUrl: string;
  forecastId: string | null;
  modelReleaseId: string | null;
  windowStart: Date | null;
  windowEnd: Date | null;
  probabilityM1Plus24h: number | null;
  expectedM1PlusCount24h: number | null;
  probabilityM4Plus24h: number | null;
  probabilityM5Plus24h: number | null;
  activityRadiusMedianKm24h: number | null;
  maximumMagnitudeQ05_24h: number | null;
  maximumMagnitudeQ50_24h: number | null;
  maximumMagnitudeQ95_24h: number | null;
  predictionSkipReason?: string | null;
  predictionStatus?: string | null;
}

const resultColumns = `
  r.event_id AS "eventId",
  r.event_revision_id AS "eventRevisionId",
  r.event_time AS "eventTime",
  r.magnitude::double precision AS magnitude,
  r.latitude::double precision AS latitude,
  r.longitude::double precision AS longitude,
  r.depth_km::double precision AS "depthKm",
  r.location_description AS "locationDescription",
  r.origin,
  r.source_url AS "sourceUrl",
  current_forecast.forecast_id AS "forecastId",
  current_forecast.model_release_id AS "modelReleaseId",
  current_forecast.window_start AS "windowStart",
  current_forecast.window_end AS "windowEnd",
  current_forecast.probability_m1_plus_24h AS "probabilityM1Plus24h",
  current_forecast.expected_m1_plus_count_24h AS "expectedM1PlusCount24h",
  current_forecast.probability_m4_plus_24h AS "probabilityM4Plus24h",
  current_forecast.probability_m5_plus_24h AS "probabilityM5Plus24h",
  current_forecast.activity_radius_median_km_24h AS "activityRadiusMedianKm24h",
  current_forecast.maximum_magnitude_q05_24h AS "maximumMagnitudeQ05_24h",
  current_forecast.maximum_magnitude_q50_24h AS "maximumMagnitudeQ50_24h",
  current_forecast.maximum_magnitude_q95_24h AS "maximumMagnitudeQ95_24h"`;

const currentForecastJoin = `
  LEFT JOIN LATERAL (
    SELECT f.*, j.model_release_id
    FROM prediction_jobs j
    JOIN forecasts f ON f.job_id = j.job_id
    WHERE j.event_revision_id = r.event_revision_id
      AND j.model_release_id = $1::uuid
      AND j.status = 'succeeded'
    ORDER BY j.requested_at DESC, j.job_id DESC
    LIMIT 1
  ) current_forecast ON true`;

function mapRow(row: EarthquakeRow): Earthquake {
  let forecast: Forecast | null = null;
  if (row.forecastId) {
    forecast = {
      forecastId: row.forecastId,
      modelReleaseId: row.modelReleaseId!,
      windowStart: row.windowStart!.toISOString(),
      windowEnd: row.windowEnd!.toISOString(),
      probabilityM1Plus24h: row.probabilityM1Plus24h!,
      expectedM1PlusCount24h: row.expectedM1PlusCount24h!,
      probabilityM4Plus24h: row.probabilityM4Plus24h!,
      probabilityM5Plus24h: row.probabilityM5Plus24h!,
      activityRadiusMedianKm24h: row.activityRadiusMedianKm24h,
      maximumMagnitudeQ05_24h: row.maximumMagnitudeQ05_24h,
      maximumMagnitudeQ50_24h: row.maximumMagnitudeQ50_24h,
      maximumMagnitudeQ95_24h: row.maximumMagnitudeQ95_24h,
    };
  }
  return {
    eventId: row.eventId,
    eventRevisionId: row.eventRevisionId,
    eventTime: row.eventTime.toISOString(),
    magnitude: row.magnitude,
    latitude: row.latitude,
    longitude: row.longitude,
    depthKm: row.depthKm,
    locationDescription: row.locationDescription,
    origin: row.origin,
    sourceUrl: row.sourceUrl,
    forecast,
    forecastAvailability: forecastAvailability(forecast, row.predictionStatus ?? null, row.predictionSkipReason ?? null),
  };
}

export class PostgresEarthquakeReader implements EarthquakeReader {
  constructor(private readonly pool: Pool, private readonly modelReleaseId: string) {}

  private async read<T extends QueryResultRow>(sql: string, values: unknown[]): Promise<T[]> {
    try {
      return (await this.pool.query<T>(sql, values)).rows;
    } catch {
      throw new DataUnavailable();
    }
  }

  async search(criteria: EarthquakeSearch): Promise<Earthquake[]> {
    const values: unknown[] = [this.modelReleaseId];
    const add = (value: unknown): string => {
      values.push(value);
      return `$${values.length}`;
    };
    const predicates = [
      'e.superseded_by_event_id IS NULL',
      `NOT EXISTS (
        SELECT 1 FROM earthquake_event_revisions newer
        WHERE newer.event_id = r.event_id AND newer.revision_number > r.revision_number
      )`,
    ];
    if (criteria.dateFrom) predicates.push(`r.event_time >= ${add(criteria.dateFrom)}::timestamptz`);
    if (criteria.dateTo) predicates.push(`r.event_time < ${add(criteria.dateTo)}::timestamptz`);
    if (criteria.location) {
      const literal = criteria.location.replace(/[\\%_]/g, '\\$&');
      predicates.push(`r.location_description ILIKE ${add(`%${literal}%`)}`);
    }
    if (criteria.magnitudeRanges.length) {
      const ranges = criteria.magnitudeRanges.map((range) => {
        const bounds: string[] = [];
        if (range.from !== undefined) bounds.push(`r.magnitude >= ${add(range.from)}::numeric`);
        if (range.below !== undefined) bounds.push(`r.magnitude < ${add(range.below)}::numeric`);
        return `(${bounds.join(' AND ')})`;
      });
      predicates.push(`(${ranges.join(' OR ')})`);
    }
    if (criteria.cursor) {
      const time = add(criteria.cursor.eventTime);
      const id = add(criteria.cursor.eventId);
      predicates.push(`(r.event_time, r.event_id) < (${time}::timestamptz, ${id}::uuid)`);
    }
    const limit = add(criteria.limit + 1);
    const sql = `
      WITH page AS MATERIALIZED (
        SELECT r.event_id, r.event_revision_id, r.event_time, r.magnitude,
               r.latitude, r.longitude, r.depth_km, r.location_description,
               r.origin, r.source_url
        FROM earthquake_event_revisions r
        JOIN earthquake_events e ON e.event_id = r.event_id
        WHERE ${predicates.join(' AND ')}
        ORDER BY r.event_time DESC, r.event_id DESC
        LIMIT ${limit}::integer
      )
      SELECT ${resultColumns}
      FROM page r
      ${currentForecastJoin}
      ORDER BY r.event_time DESC, r.event_id DESC`;
    return (await this.read<EarthquakeRow>(sql, values)).map(mapRow);
  }

  async findById(eventId: string): Promise<Earthquake | null> {
    const sql = `
      SELECT ${resultColumns}, r.prediction_skip_reason AS "predictionSkipReason",
        latest_prediction.status AS "predictionStatus"
      FROM earthquake_events e
      JOIN LATERAL (
        SELECT r.event_id, r.event_revision_id, r.event_time, r.magnitude,
          r.latitude, r.longitude, r.depth_km, r.location_description,
          r.origin, r.source_url, r.prediction_skip_reason
        FROM earthquake_event_revisions r
        WHERE r.event_id = e.event_id
        ORDER BY r.revision_number DESC
        LIMIT 1
      ) r ON true
      ${currentForecastJoin}
      LEFT JOIN LATERAL (
        SELECT j.status
        FROM prediction_jobs j
        WHERE j.event_revision_id = r.event_revision_id AND j.model_release_id = $1::uuid
        ORDER BY j.requested_at DESC, j.job_id DESC
        LIMIT 1
      ) latest_prediction ON true
      WHERE e.event_id = $2::uuid AND e.superseded_by_event_id IS NULL`;
    const rows = await this.read<EarthquakeRow>(sql, [this.modelReleaseId, eventId]);
    return rows[0] ? mapRow(rows[0]) : null;
  }

  async check(): Promise<void> {
    const rows = await this.read('SELECT 1 FROM model_releases WHERE model_release_id = $1::uuid', [this.modelReleaseId]);
    if (rows.length !== 1) throw new DataUnavailable();
  }
}
