import type { BulletinState } from '../../lib/bulletin-navigation';
import type { components } from '../../lib/api/schema';
import { magnitudeRangesForBands } from '../../lib/magnitude.ts';

export type SearchRequest = components['schemas']['SearchRequest'];
export type SearchResponse = components['schemas']['SearchResponse'];
export type SearchEvents = (request: SearchRequest, signal: AbortSignal) => Promise<SearchResponse>;

export function eventSearch(state: BulletinState): SearchRequest {
  return {
    limit: 30,
    location: state.query.trim() || undefined,
    dateFrom: state.date.from,
    dateTo: state.date.to,
    magnitudeRanges: magnitudeRangesForBands(state.magnitudes),
  };
}
