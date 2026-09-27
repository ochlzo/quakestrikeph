import type { EarthquakeSearch, MagnitudeRange, SearchCursor } from '../../domain/information.js';
import { validMagnitudeRange } from '../../domain/information.js';

export class InvalidRequest extends Error {}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const isoWithOffset = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?(Z|([+-])(\d{2}):(\d{2}))$/;

export function validEventId(value: string): boolean {
  return uuid.test(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, allowed: string[]): boolean {
  return Object.keys(value).every((key) => allowed.includes(key));
}

function timestamp(value: unknown, field: string): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== 'string') throw new InvalidRequest(`${field} must be an ISO 8601 timestamp with an offset`);
  const match = isoWithOffset.exec(value);
  if (!match) throw new InvalidRequest(`${field} must be an ISO 8601 timestamp with an offset`);
  const [, year, month, day, hour, minute, second, fraction, zone, sign, offsetHour, offsetMinute] = match;
  const y = Number(year), mo = Number(month), d = Number(day), h = Number(hour), mi = Number(minute), s = Number(second);
  const calendar = new Date(Date.UTC(y, mo - 1, d, h, mi, s));
  if (calendar.getUTCFullYear() !== y || calendar.getUTCMonth() + 1 !== mo || calendar.getUTCDate() !== d ||
      calendar.getUTCHours() !== h || calendar.getUTCMinutes() !== mi || calendar.getUTCSeconds() !== s ||
      (zone !== 'Z' && (Number(offsetHour) > 23 || Number(offsetMinute) > 59))) {
    throw new InvalidRequest(`${field} is not a valid timestamp`);
  }
  const offset = zone === 'Z' ? 0 : (sign === '+' ? 1 : -1) * (Number(offsetHour) * 60 + Number(offsetMinute));
  return new Date(calendar.getTime() + Number((fraction ?? '').padEnd(3, '0')) - offset * 60_000).toISOString();
}

export function encodeCursor(cursor: SearchCursor): string {
  return Buffer.from(JSON.stringify([cursor.eventTime, cursor.eventId])).toString('base64url');
}

function decodeCursor(value: unknown): SearchCursor | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== 'string' || value.length > 256 || !/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new InvalidRequest('cursor is invalid');
  }
  try {
    const decoded: unknown = JSON.parse(Buffer.from(value, 'base64url').toString('utf8'));
    if (!Array.isArray(decoded) || decoded.length !== 2 || typeof decoded[0] !== 'string' ||
        typeof decoded[1] !== 'string' || !validEventId(decoded[1]) ||
        new Date(decoded[0]).toISOString() !== decoded[0]) {
      throw new Error('bad cursor');
    }
    return { eventTime: decoded[0], eventId: decoded[1] };
  } catch {
    throw new InvalidRequest('cursor is invalid');
  }
}

export function parseSearchRequest(body: unknown): EarthquakeSearch {
  if (!isRecord(body) || !exactKeys(body, ['magnitudeRanges', 'dateFrom', 'dateTo', 'location', 'limit', 'cursor'])) {
    throw new InvalidRequest('Search body has unknown or invalid fields');
  }
  let magnitudeRanges: MagnitudeRange[] = [];
  if (body.magnitudeRanges !== undefined) {
    if (!Array.isArray(body.magnitudeRanges) || body.magnitudeRanges.length > 8) {
      throw new InvalidRequest('magnitudeRanges must contain at most 8 ranges');
    }
    magnitudeRanges = body.magnitudeRanges.map((value: unknown) => {
      if (!isRecord(value) || !exactKeys(value, ['from', 'below']) || !validMagnitudeRange(value as MagnitudeRange)) {
        throw new InvalidRequest('Each magnitude range needs finite from or below bounds, with from below below');
      }
      return value as MagnitudeRange;
    });
  }
  const dateFrom = timestamp(body.dateFrom, 'dateFrom');
  const dateTo = timestamp(body.dateTo, 'dateTo');
  if (dateFrom && dateTo && dateFrom >= dateTo) throw new InvalidRequest('dateFrom must be before dateTo');
  let location: string | undefined;
  if (body.location !== undefined) {
    if (typeof body.location !== 'string') throw new InvalidRequest('location must be text');
    location = body.location.trim();
    if (location.length < 2 || location.length > 100) throw new InvalidRequest('location must be 2 to 100 characters');
  }
  let limit = 25;
  if (body.limit !== undefined) {
    if (!Number.isInteger(body.limit) || (body.limit as number) < 1 || (body.limit as number) > 100) {
      throw new InvalidRequest('limit must be an integer from 1 to 100');
    }
    limit = body.limit as number;
  }
  return { magnitudeRanges, dateFrom, dateTo, location, limit, cursor: decodeCursor(body.cursor) };
}
