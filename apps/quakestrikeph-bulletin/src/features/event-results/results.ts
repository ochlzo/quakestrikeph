import { matchesBulletinFilters, type BulletinState } from '../../lib/bulletin-navigation.ts';
import type { Earthquake, EarthquakeDetail } from '../../lib/events';
import type { readEarthquakeCache, writeEarthquakeCache } from '../../lib/earthquake-cache';
import { eventSearch, type SearchEvents, type SearchResponse } from './search.ts';

type Filters = Pick<BulletinState, 'query' | 'date' | 'magnitudes'>;
type Status = 'restoring' | 'loading' | 'ready' | 'error';
type PageStatus = 'idle' | 'loading' | 'error';
type DetailStatus = 'loading' | 'ready' | 'error';
type Dependencies = {
  search: SearchEvents;
  detail: (eventId: string, signal: AbortSignal) => Promise<EarthquakeDetail>;
  readCache: typeof readEarthquakeCache;
  writeCache: typeof writeEarthquakeCache;
  refreshFailed: () => void;
};

export type EventResultsSnapshot = {
  state: BulletinState;
  events: Earthquake[];
  selected: Earthquake | undefined;
  selectedDetail: EarthquakeDetail | null;
  status: Status;
  pageStatus: PageStatus;
  detailStatus: DetailStatus;
  previousId: string | null;
  resultsCurrent: boolean;
  searching: boolean;
  failed: boolean;
  canLoadMore: boolean;
};

function sameBands(left: string[], right: string[]) {
  return left.length === right.length && left.every((band, index) => band === right[index]);
}

function sameFilters(left: Filters, right: Filters) {
  return left.query.trim() === right.query.trim() &&
    left.date.value === right.date.value && left.date.from === right.date.from && left.date.to === right.date.to &&
    sameBands(left.magnitudes, right.magnitudes);
}

// One mounted Bulletin owns one controller. Construction is safe during server rendering.
export class EventResults {
  private state: BulletinState;
  private settled: Filters;
  private events: Earthquake[];
  private selectedDetail: EarthquakeDetail | null = null;
  private status: Status;
  private pageStatus: PageStatus = 'idle';
  private detailStatus: DetailStatus = 'loading';
  private previousId: string | null = null;
  private nextCursor: string | null = null;
  private initialPage: SearchResponse | null;
  private active = false;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private searchController: AbortController | undefined;
  private pageController: AbortController | undefined;
  private detailController: AbortController | undefined;
  private listeners = new Set<() => void>();
  private dependencies: Dependencies;
  private initialSnapshot: EventResultsSnapshot;
  private snapshot: EventResultsSnapshot;

  constructor(state: BulletinState, initialResults: SearchResponse | null, dependencies: Dependencies) {
    this.state = { ...state, date: { ...state.date }, magnitudes: [...state.magnitudes] };
    this.settled = this.state;
    this.events = initialResults?.items ?? [];
    this.initialPage = initialResults;
    this.status = initialResults ? 'ready' : 'restoring';
    this.dependencies = dependencies;
    this.snapshot = this.makeSnapshot();
    this.initialSnapshot = this.snapshot;
  }

  getSnapshot = () => this.snapshot;
  getServerSnapshot = () => this.initialSnapshot;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  start = () => {
    if (this.active) return;
    this.active = true;
    this.loadEvents(true);
    this.loadDetail();
  };

  stop = () => {
    this.active = false;
    clearTimeout(this.timer);
    this.searchController?.abort();
    this.pageController?.abort();
    this.detailController?.abort();
  };

  changeFilters = (patch: Partial<Filters>) => {
    const next = { ...this.state, ...patch };
    const changed = !sameFilters(this.state, next);
    if (!changed && next.query === this.state.query) return;
    this.state = changed ? { ...next, selectedId: null } : next;
    if (changed) {
      this.previousId = null;
      this.detailController?.abort();
      this.selectedDetail = null;
      this.searchController?.abort();
      this.pageController?.abort();
      this.nextCursor = null;
      this.pageStatus = 'idle';
    }
    this.publish();
    if (changed) this.refresh();
  };

  select = (eventId: string) => {
    if (eventId === this.snapshot.selected?.eventId) return;
    this.previousId = this.snapshot.selected?.eventId ?? null;
    this.state = { ...this.state, selectedId: eventId };
    this.detailController?.abort();
    this.selectedDetail = null;
    this.detailStatus = 'loading';
    this.publish();
    if (this.active) this.loadDetail();
  };

  refresh = () => this.loadEvents();

  private loadEvents(resuming = false) {
    if (!this.active) return;
    clearTimeout(this.timer);
    this.searchController?.abort();
    this.pageController?.abort();
    this.pageController = undefined;
    this.pageStatus = 'idle';
    this.nextCursor = null;
    const state = this.state;
    if (state.query.trim().length === 1) { this.publish(); return; }
    const delay = state.query.trim() || !sameBands(state.magnitudes, this.settled.magnitudes) ? 300 : 0;
    const search = eventSearch(state);
    const initial = sameFilters(state, this.initialSnapshot.state) ? this.initialPage : null;
    this.initialPage = null;
    const retained = resuming && this.status === 'ready' && sameFilters(state, this.settled);
    const cached = initial || retained ? null : this.dependencies.readCache(search);
    if (initial) this.dependencies.writeCache(search, initial);
    if (cached) {
      this.events = cached.items;
      this.settled = state;
      this.status = 'ready';
    } else if (!initial && !retained) this.status = 'loading';
    const controller = new AbortController();
    this.searchController = controller;
    this.publish();
    this.timer = setTimeout(async () => {
      try {
        const data = await this.dependencies.search(search, controller.signal);
        if (controller.signal.aborted || !this.active) return;
        this.dependencies.writeCache(search, data);
        if (JSON.stringify(this.events) !== JSON.stringify(data.items)) this.events = data.items;
        this.nextCursor = data.nextCursor;
        this.settled = state;
        this.previousId = null;
        this.status = 'ready';
        this.publish();
      } catch {
        if (controller.signal.aborted || !this.active) return;
        if (cached || initial || retained) { this.dependencies.refreshFailed(); return; }
        this.settled = state;
        this.status = 'error';
        this.publish();
      }
    }, delay);
  }

  loadMore = async () => {
    if (!this.active || !this.snapshot.canLoadMore || this.pageController) return;
    const controller = new AbortController();
    this.pageController = controller;
    this.pageStatus = 'loading';
    const search = { ...eventSearch(this.state), cursor: this.nextCursor! };
    this.publish();
    try {
      const data = await this.dependencies.search(search, controller.signal);
      if (controller.signal.aborted || !this.active) return;
      const seen = new Set(this.events.map(event => event.eventId));
      this.events = [...this.events, ...data.items.filter(event => !seen.has(event.eventId))];
      this.nextCursor = data.nextCursor;
      this.pageStatus = 'idle';
      this.publish();
    } catch {
      if (!controller.signal.aborted && this.active) {
        this.pageStatus = 'error';
        this.publish();
      }
    } finally {
      if (this.pageController === controller) this.pageController = undefined;
    }
  };

  private loadDetail() {
    const eventId = this.state.selectedId;
    if (!eventId) return;
    this.detailController?.abort();
    const controller = new AbortController();
    this.detailController = controller;
    this.selectedDetail = null;
    this.detailStatus = 'loading';
    this.publish();
    this.dependencies.detail(eventId, controller.signal).then(data => {
      if (controller.signal.aborted || !this.active) return;
      this.selectedDetail = data;
      this.detailStatus = 'ready';
      this.publish();
    }).catch(() => {
      if (controller.signal.aborted || !this.active) return;
      this.selectedDetail = null;
      this.detailStatus = 'error';
      this.publish();
    });
  }

  private makeSnapshot(): EventResultsSnapshot {
    const matches = sameFilters(this.settled, this.state);
    const resultsCurrent = this.status === 'ready' && matches;
    const detail = this.selectedDetail;
    // A restored selection can be older than the first search page.
    const restored = detail && detail.eventId === this.state.selectedId &&
      !this.events.some(event => event.eventId === detail.eventId) && matchesBulletinFilters(detail, this.state)
      ? detail : null;
    const events = resultsCurrent ? (restored ? [...this.events, restored] : this.events) : [];
    return {
      state: this.state, events, selected: events.find(event => event.eventId === this.state.selectedId),
      selectedDetail: detail, status: this.status, pageStatus: this.pageStatus, detailStatus: this.detailStatus,
      previousId: this.previousId, resultsCurrent,
      searching: this.state.query.trim().length !== 1 && (this.status === 'loading' || !matches),
      failed: this.status === 'error' && matches,
      canLoadMore: resultsCurrent && Boolean(this.nextCursor),
    };
  }

  private publish() {
    this.snapshot = this.makeSnapshot();
    this.listeners.forEach(listener => listener());
  }
}
