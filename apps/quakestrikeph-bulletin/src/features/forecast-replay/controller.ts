import type { Earthquake, EarthquakeDetail } from "../../lib/events.ts";
import { ForecastObservationCache } from "../../lib/forecast-observation-cache.ts";

export type ReplaySnapshot = {
  replayMinutes: number;
  rangeStartMinutes: number;
  availableThrough: number;
  playbackSpeed: 1 | 2;
  playing: boolean;
  ready: boolean;
  observations: Earthquake[];
  loadStatus: "loading" | "complete" | "incomplete";
};

type Dependencies = {
  load: (from: string, to: string) => Promise<Earthquake[]>;
  now: () => number;
  onChange: (snapshot: ReplaySnapshot) => void;
  onLoadError: () => void;
  onLoadSuccess: () => void;
};

export class ReplayController {
  readonly origin: number;
  readonly endMinutes: number;
  private cache: ForecastObservationCache;
  private state: ReplaySnapshot;
  private eventId: string;
  private dependencies: Dependencies;
  private timer: ReturnType<typeof setInterval> | null = null;
  private loadTimer: ReturnType<typeof setTimeout> | null = null;
  private requested: { key: string; revision: number } | null = null;
  private revision = 0;
  private started = false;
  private disposed = false;

  constructor(event: EarthquakeDetail, dependencies: Dependencies) {
    if (!event.forecast) throw new Error("Replay requires a forecast");
    this.origin = Date.parse(event.forecast.windowStart);
    this.endMinutes = (Date.parse(event.forecast.windowEnd) - this.origin) / 60000;
    this.eventId = event.eventId;
    this.dependencies = dependencies;
    this.cache = new ForecastObservationCache(this.origin, dependencies.load);
    this.state = {
      replayMinutes: 0, rangeStartMinutes: 0, availableThrough: dependencies.now(),
      playbackSpeed: 1, playing: false, ready: false, observations: [], loadStatus: "loading",
    };
  }

  get snapshot() { return this.state; }

  private publish(patch: Partial<ReplaySnapshot>) {
    if (this.disposed) return;
    this.state = { ...this.state, ...patch };
    this.dependencies.onChange(this.state);
  }

  private time(minutes: number) { return this.origin + minutes * 60000; }
  private nowMinutes() { return (this.state.availableThrough - this.origin) / 60000; }
  private playbackEnd() {
    return this.state.replayMinutes < this.endMinutes
      ? Math.min(this.endMinutes, this.nowMinutes()) : this.nowMinutes();
  }

  private paint(patch: Partial<ReplaySnapshot> = {}) {
    const next = { ...this.state, ...patch };
    const from = this.time(next.rangeStartMinutes), to = this.time(next.replayMinutes);
    this.publish({
      ...patch,
      observations: this.cache.observations(from, Math.min(to, next.availableThrough), this.eventId),
      loadStatus: this.cache.covered(from, to, next.availableThrough) ? "complete" : "loading",
    });
  }

  private loadingFailed() {
    this.setPlaying(false);
    this.paint();
    this.publish({ loadStatus: "incomplete" });
    this.dependencies.onLoadError();
  }

  private requestObservations(prefetch = false) {
    if (this.disposed) return;
    const from = this.time(this.state.rangeStartMinutes);
    const to = this.time(prefetch
      ? Math.min(this.state.replayMinutes + 120, this.playbackEnd()) : this.state.replayMinutes);
    const key = `${Math.floor((from - this.origin) / 86400000)}:${Math.floor((to - this.origin) / 86400000)}`;
    if (this.cache.covered(from, to, this.state.availableThrough) || this.requested?.key === key) return;
    const request = { key, revision: this.revision };
    this.requested = request;
    const isCurrent = () => !this.disposed && request.revision === this.revision;
    void this.cache.ensure(from, to, this.state.availableThrough, isCurrent)
      .then(() => {
        if (isCurrent()) {
          this.paint();
          this.dependencies.onLoadSuccess();
        }
      })
      .catch(() => { if (isCurrent()) this.loadingFailed(); })
      .finally(() => {
        // An obsolete request must not clear a newer request for the same chunks.
        if (this.requested === request) this.requested = null;
      });
  }

  start() {
    if (this.started || this.disposed) return;
    this.started = true;
    void this.cache.ensure(this.origin, this.origin + 86400000 - 1, this.state.availableThrough, () => !this.disposed)
      .then(() => {
        if (this.disposed) return;
        // A selection made during startup remains the selection painted on completion.
        this.paint({ ready: true });
      })
      .catch(() => {
        if (this.disposed) return;
        this.publish({ ready: true });
        if (this.revision === 0) this.loadingFailed();
      });
  }

  refreshNow() {
    this.publish({ availableThrough: this.dependencies.now() });
  }

  setPlaying(playing: boolean) {
    if (this.disposed) return;
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    playing = playing && this.state.ready && this.state.replayMinutes < this.playbackEnd();
    this.publish({ playing });
    if (!playing) return;
    this.requestObservations(true);
    this.timer = setInterval(() => {
      const limit = this.playbackEnd();
      const next = Math.min(this.state.replayMinutes + 6 * this.state.playbackSpeed, limit);
      if (!this.cache.covered(this.time(this.state.rangeStartMinutes), this.time(next), this.state.availableThrough)) {
        this.requestObservations(true);
        this.publish({ loadStatus: "loading" });
        return;
      }
      this.paint({ replayMinutes: next });
      if (next >= limit) this.setPlaying(false);
      else this.requestObservations(true);
    }, 100);
  }

  setPlaybackSpeed(playbackSpeed: 1 | 2) { this.publish({ playbackSpeed }); }

  seek(handle: "history" | "replay", minutes: number) {
    if (this.disposed) return;
    this.setPlaying(false);
    this.refreshNow();
    const snapped = Math.round(minutes / 15) * 15;
    const target = handle === "history"
      ? Math.min(snapped, this.state.replayMinutes)
      : Math.min(Math.max(snapped, this.state.rangeStartMinutes), this.nowMinutes());
    if (target === (handle === "history" ? this.state.rangeStartMinutes : this.state.replayMinutes)) return;
    this.revision++;
    this.requested = null;
    this.paint(handle === "history" ? { rangeStartMinutes: target } : { replayMinutes: target });
    if (this.loadTimer !== null) clearTimeout(this.loadTimer);
    this.loadTimer = setTimeout(() => this.requestObservations(), 150);
  }

  reset() {
    if (this.disposed) return;
    this.setPlaying(false);
    this.revision++;
    this.requested = null;
    if (this.loadTimer !== null) clearTimeout(this.loadTimer);
    this.loadTimer = null;
    this.refreshNow();
    this.paint({ replayMinutes: 0, rangeStartMinutes: 0 });
    this.requestObservations();
  }

  retry() {
    if (this.disposed) return;
    this.requested = null;
    this.requestObservations();
  }

  dispose() {
    this.disposed = true;
    this.cache.clear();
    this.revision++;
    if (this.timer !== null) clearInterval(this.timer);
    if (this.loadTimer !== null) clearTimeout(this.loadTimer);
    this.timer = this.loadTimer = null;
  }
}
