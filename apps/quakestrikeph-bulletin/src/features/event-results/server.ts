import type { BulletinState } from '../../lib/bulletin-navigation';
import { eventSearch, type SearchEvents, type SearchResponse } from './search.ts';

export async function prepareEventResults(state: BulletinState, search: SearchEvents): Promise<SearchResponse | null> {
  const filters = state.query.trim().length < 2 ? { ...state, query: '' } : state;
  try {
    const data = await search(eventSearch(filters), AbortSignal.timeout(1500));
    return { ...data, items: data.items.slice(0, 30) };
  } catch {
    // The browser can restore saved rows and retry when initialization fails.
    return null;
  }
}
