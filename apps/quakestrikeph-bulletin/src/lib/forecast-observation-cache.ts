import type { Earthquake } from "./events";

const day = 86_400_000;
type Chunk = { end: number; items: Earthquake[] };

// Search intervals are [from, to); replay includes the observation at its exact instant.
export class ForecastObservationCache {
  private chunks = new Map<number, Chunk>();
  private pending = new Map<number, Promise<void>>();
  private generation = 0;
  private origin: number;
  private load: (from: string, to: string) => Promise<Earthquake[]>;
  constructor(
    origin: number,
    load: (from: string, to: string) => Promise<Earthquake[]>,
  ) {
    this.origin = origin;
    this.load = load;
  }

  clear() {
    this.generation++;
    this.chunks.clear();
    this.pending.clear();
  }

  private keys(from: number, to: number, now: number) {
    const end = Math.min(to + 1, now + 1);
    const keys: number[] = [];
    for (
      let key = Math.floor((from - this.origin) / day);
      this.origin + key * day < end;
      key++
    )
      keys.push(key);
    return keys;
  }

  covered(from: number, to: number, now = Date.now()) {
    return this.keys(from, to, now).every(
      (key) =>
        (this.chunks.get(key)?.end ?? -Infinity) >=
        Math.min(this.origin + (key + 1) * day, to + 1, now + 1),
    );
  }

  async ensure(
    from: number,
    to: number,
    now = Date.now(),
    isCurrent = () => true,
  ) {
    // Fetch sequentially so a long history selection cannot flood the Backend.
    for (const key of this.keys(from, to, now)) {
      const start = this.origin + key * day;
      const end = Math.min(start + day, now + 1);
      if (!isCurrent()) return;
      while ((this.chunks.get(key)?.end ?? -Infinity) < end && isCurrent()) {
        let request = this.pending.get(key);
        if (!request) {
          const generation = this.generation;
          request = this.load(
            new Date(start).toISOString(),
            new Date(end).toISOString(),
          )
            .then((items) => {
              if (generation === this.generation) this.chunks.set(key, { end, items });
            })
            .finally(() => { if (generation === this.generation) this.pending.delete(key); });
          this.pending.set(key, request);
        }
        await request;
      }
    }
  }

  observations(from: number, to: number, anchorId: string) {
    const items = new Map<string, Earthquake>();
    for (const chunk of this.chunks.values())
      for (const item of chunk.items) {
        const time = Date.parse(item.eventTime);
        if (item.eventId !== anchorId && time >= from && time <= to)
          items.set(item.eventId, item);
      }
    return [...items.values()].sort(
      (a, b) => Date.parse(a.eventTime) - Date.parse(b.eventTime),
    );
  }
}
