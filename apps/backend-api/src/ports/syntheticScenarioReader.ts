import type { SyntheticScenario } from '../domain/submittedScenario.js';

// Null establishes absence; failures must throw DataUnavailable.
export interface SyntheticScenarioReader {
  findSubmitted(eventId: string): Promise<SyntheticScenario | null>;
}
