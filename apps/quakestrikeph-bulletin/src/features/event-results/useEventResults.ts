import { useEffect, useState, useSyncExternalStore } from 'react';
import { toast } from '../../components/ui/toast';
import { searchEvents, readEventDetail } from '../../lib/api/event-results';
import { bulletinParams, type BulletinState } from '../../lib/bulletin-navigation';
import { readEarthquakeCache, writeEarthquakeCache } from '../../lib/earthquake-cache';
import { EventResults } from './results';
import type { SearchResponse } from './search';

export function useEventResults(initialState: BulletinState, initialResults: SearchResponse | null) {
  const [results] = useState(() => new EventResults(initialState, initialResults, {
    search: searchEvents, detail: readEventDetail,
    readCache: readEarthquakeCache, writeCache: writeEarthquakeCache,
    refreshFailed: () => toast.add({ type: 'error', title: 'Earthquakes could not be refreshed.',
      description: 'Showing saved results. Reload to try again.' }),
  }));
  const snapshot = useSyncExternalStore(results.subscribe, results.getSnapshot, results.getServerSnapshot);
  useEffect(() => {
    results.start();
    const restored = (event: PageTransitionEvent) => { if (event.persisted) results.refresh(); };
    window.addEventListener('pageshow', restored);
    return () => {
      window.removeEventListener('pageshow', restored);
      results.stop();
    };
  }, [results]);
  useEffect(() => {
    if (window.location.pathname !== '/') return;
    const url = new URL(window.location.href);
    for (const key of ['q', 'date', 'from', 'to', 'magnitudes', 'selected']) url.searchParams.delete(key);
    bulletinParams(snapshot.state).forEach((value, key) => url.searchParams.set(key, value));
    window.history.replaceState(window.history.state, '', url);
  }, [snapshot.state]);
  return { ...snapshot, changeFilters: results.changeFilters, select: results.select,
    refresh: results.refresh, nextPage: results.nextPage,
    previousPage: results.previousPage, changePageSize: results.changePageSize };
}
