import type { Earthquake, EarthquakeSearch } from '../domain/information.js';

export interface EarthquakeReader {
  search(criteria: EarthquakeSearch): Promise<Earthquake[]>;
  findById(eventId: string): Promise<Earthquake | null>;
  check(): Promise<void>;
}
