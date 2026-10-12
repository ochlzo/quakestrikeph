import { magnitudeBands, magnitudeRangesForBands } from './magnitude.ts';
import type { Earthquake } from './events';

export type DateFilter = { value: string; from?: string; to?: string };
export type BulletinState = {
  query: string;
  date: DateFilter;
  magnitudes: string[];
  selectedId: string | null;
};

export function validEventId(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function timestamp(value: string | null): string | undefined {
  if (!value || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return;
  const time = Date.parse(value);
  if (Number.isFinite(time)) return new Date(time).toISOString();
}

export function readBulletinState(params: URLSearchParams): BulletinState {
  const value = params.get('date');
  const from = timestamp(params.get('from'));
  const to = timestamp(params.get('to'));
  let date: DateFilter = { value: 'all' };
  if (value === 'custom' && from && to && from < to) date = { value, from, to };
  else if (value && ['1', '7', '30'].includes(value)) {
    date = { value, from: from ?? new Date(Date.now() - Number(value) * 86400000).toISOString() };
  }
  const selected = params.get('selected') ?? '';
  const requestedBands = params.get('magnitudes')?.split(',') ?? [];
  return {
    query: (params.get('q') ?? '').slice(0, 100),
    date,
    magnitudes: magnitudeBands.filter(band => requestedBands.includes(band.className)).map(band => band.className),
    selectedId: validEventId(selected) ? selected.toLowerCase() : null,
  };
}

export function bulletinParams(state: BulletinState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.query) params.set('q', state.query);
  if (state.date.value !== 'all') params.set('date', state.date.value);
  if (state.date.from) params.set('from', state.date.from);
  if (state.date.to) params.set('to', state.date.to);
  if (state.magnitudes.length) params.set('magnitudes', state.magnitudes.join(','));
  if (state.selectedId) params.set('selected', state.selectedId);
  return params;
}

export function matchesBulletinFilters(event: Earthquake, state: BulletinState): boolean {
  const time = Date.parse(event.eventTime);
  const ranges = magnitudeRangesForBands(state.magnitudes);
  return event.locationDescription.toLowerCase().includes(state.query.trim().toLowerCase()) &&
    (!state.date.from || time >= Date.parse(state.date.from)) &&
    (!state.date.to || time < Date.parse(state.date.to)) &&
    (!ranges || ranges.some(range => event.magnitude >= (range.from ?? -Infinity) && event.magnitude < (range.below ?? Infinity)));
}
