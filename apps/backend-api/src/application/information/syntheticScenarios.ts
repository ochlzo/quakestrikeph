import type { EarthquakeSearch } from '../../domain/information.js';
import type { SyntheticScenarioReader } from '../../ports/syntheticScenarioReader.js';
import type { SearchPage } from './earthquakes.js';
import { DataUnavailable } from './errors.js';

export async function readSyntheticScenario(reader: SyntheticScenarioReader | undefined, eventId: string) {
  if (!reader) throw new DataUnavailable('Synthetic storage is not configured');
  return reader.findSubmitted(eventId);
}

export async function searchSyntheticObservations(
  reader: SyntheticScenarioReader | undefined, eventId: string, criteria: EarthquakeSearch,
): Promise<SearchPage | null> {
  const scenario = await readSyntheticScenario(reader, eventId);
  if (!scenario) return null;
  const rows = scenario.observations.filter(item =>
    (!criteria.dateFrom || item.eventTime >= criteria.dateFrom) &&
    (!criteria.dateTo || item.eventTime < criteria.dateTo) &&
    (!criteria.cursor || item.eventTime < criteria.cursor.eventTime ||
      (item.eventTime === criteria.cursor.eventTime && item.eventId < criteria.cursor.eventId)))
    .sort((a, b) => b.eventTime.localeCompare(a.eventTime) || b.eventId.localeCompare(a.eventId));
  const items = rows.slice(0, criteria.limit);
  const last = items.at(-1);
  const hasMore = rows.length > criteria.limit;
  return { items, hasMore, nextCursor: hasMore && last ? { eventTime: last.eventTime, eventId: last.eventId } : null };
}
