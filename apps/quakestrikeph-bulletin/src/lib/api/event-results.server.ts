import { getSecret } from 'astro:env/server';
import type { components } from './schema';

export async function searchInitialEvents(body: components['schemas']['SearchRequest'], signal: AbortSignal): Promise<components['schemas']['SearchResponse']> {
  const response = await fetch(new URL('/api/v1/earthquakes/search', getSecret('API_TARGET') || 'https://quakestrikeph.qzz.io'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  });
  if (!response.ok) throw new Error('Search failed');
  return response.json();
}
