import type { components } from './schema';

type Earthquake = components['schemas']['EarthquakeSummary'];

export async function loadObservationWindow(dateFrom: string, dateTo: string): Promise<Earthquake[]> {
  const items: Earthquake[] = [];
  const cursors = new Set<string>();
  const signal = AbortSignal.timeout(10000);
  let cursor: string | null = null;
  do {
    const response = await fetch('/api/v1/earthquakes/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: 100, dateFrom, dateTo, ...(cursor ? { cursor } : {}) }),
      signal,
    });
    if (!response.ok) throw new Error('Observed earthquakes unavailable');
    const data: components['schemas']['SearchResponse'] = await response.json();
    if (!Array.isArray(data.items) || typeof data.hasMore !== 'boolean') throw new Error('Invalid observation response');
    items.push(...data.items);
    cursor = data.hasMore ? data.nextCursor : null;
    if (data.hasMore && (!cursor || cursors.has(cursor))) throw new Error('Invalid observation cursor');
    if (cursor) cursors.add(cursor);
  } while (cursor);
  return items.sort((a, b) => Date.parse(a.eventTime) - Date.parse(b.eventTime));
}
