import type { Earthquake, EarthquakeSearch, SearchCursor } from '../../domain/information.js';
import type { EarthquakeReader } from '../../ports/earthquakeReader.js';

export interface SearchPage {
  items: Earthquake[];
  hasMore: boolean;
  nextCursor: SearchCursor | null;
}

export async function searchEarthquakes(reader: EarthquakeReader, criteria: EarthquakeSearch): Promise<SearchPage> {
  const rows = await reader.search(criteria);
  const items = rows.slice(0, criteria.limit);
  const last = items.at(-1);
  const hasMore = rows.length > criteria.limit;
  return {
    items,
    hasMore,
    nextCursor: hasMore && last ? { eventTime: last.eventTime, eventId: last.eventId } : null,
  };
}
