import { bulletinApi } from './client';
import type { components } from './schema';

export async function searchEvents(body: components['schemas']['SearchRequest'], signal: AbortSignal) {
  const { data } = await bulletinApi.POST('/earthquakes/search', { body, signal });
  if (!data) throw new Error('Search failed');
  return data;
}

export async function readEventDetail(eventId: string, signal: AbortSignal) {
  const { data } = await bulletinApi.GET('/earthquakes/{eventId}', {
    params: { path: { eventId } }, signal,
  });
  if (!data) throw new Error('Detail failed');
  return data.item;
}
