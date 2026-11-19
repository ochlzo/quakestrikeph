import { createHmac, randomUUID, timingSafeEqual } from 'node:crypto';

export const guestCookieName = 'qs_guest';
export const guestCookieLifetimeMs = 24 * 60 * 60 * 1000;

const scenarioBounds = {
  latitude: [0, 26],
  longitude: [110, 135],
  magnitude: [1, 10],
  depthKm: [0, 700],
} as const;

type ScenarioField = keyof typeof scenarioBounds;
export type SimulationScenario = Record<ScenarioField, number>;

export class InvalidSimulationScenario extends Error {
  constructor(message: string, readonly field?: ScenarioField) { super(message); }
}

export function simulationScenario(body: unknown): SimulationScenario {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    throw new InvalidSimulationScenario('Enter a simulation scenario.');
  }
  const values = body as Record<string, unknown>;
  const fields = Object.keys(scenarioBounds) as ScenarioField[];
  for (const field of fields) {
    const value = values[field];
    const [minimum, maximum] = scenarioBounds[field];
    if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum) {
      throw new InvalidSimulationScenario(`Enter a value between ${minimum} and ${maximum}.`, field);
    }
  }
  if (Object.keys(values).length !== fields.length) {
    throw new InvalidSimulationScenario('The scenario contains an unexpected field.');
  }
  return values as SimulationScenario;
}

export class SimulationGuestCookies {
  constructor(private readonly key: string) {}

  issue(now: Date): string {
    const claims = `${randomUUID()}.${now.getTime()}`;
    return `${claims}.${this.sign(claims).toString('base64url')}`;
  }

  identify(header: string | undefined, now: Date): string | undefined {
    const cookies = header?.split(';').map(cookie => cookie.trim()) ?? [];
    const matches = cookies.filter(cookie => cookie.startsWith(`${guestCookieName}=`));
    if (matches.length !== 1) return undefined;
    const token = matches[0]!.slice(guestCookieName.length + 1);
    const claims = /^([a-f0-9-]{36})\.(\d{1,15})\.([\w-]{43})$/.exec(token);
    if (!claims) return undefined;
    const [, guestId, issued, signature] = claims;
    const issuedAt = Number(issued);
    if (now.getTime() < issuedAt || now.getTime() >= issuedAt + guestCookieLifetimeMs) return undefined;
    const expected = this.sign(`${guestId}.${issued}`).toString('base64url');
    return timingSafeEqual(Buffer.from(signature!), Buffer.from(expected)) ? guestId : undefined;
  }

  private sign(claims: string) { return createHmac('sha256', this.key).update(claims).digest(); }
}

export type SimulationCatalog =
  | { status: 'current' | 'stale' | 'too_old'; catalogCutoff: string }
  | { status: 'insufficient_history' | 'unavailable'; catalogCutoff: null };

export interface SimulationRequest {
  scenario: SimulationScenario;
  guestId: string;
  clientIp: string;
}

export interface SimulationResult {
  scenario: SimulationScenario;
  catalogCutoff: string;
  forecast: {
    windowStart: string;
    windowEnd: string;
    probabilityM1Plus24h: number;
    probabilityM4Plus24h: number;
    probabilityM5Plus24h: number;
    expectedM1PlusCount24h: number;
    maximumMagnitudeQ05_24h: number | null;
    maximumMagnitudeQ50_24h: number | null;
    maximumMagnitudeQ95_24h: number | null;
    activityRadiusMedianKm24h: number | null;
  };
}

export type SimulationRun =
  | { status: 200; body: SimulationResult }
  | { status: 429; body: { error: { code: 'SIMULATION_LIMIT_REACHED'; message: string; retryAt: string } }; retryAfter: number }
  | { status: 500 | 503 | 504; body: { error: { code: string; message: string; catalogCutoff?: string } } };

export interface ForecastSimulator {
  catalog(): Promise<SimulationCatalog>;
  run(request: SimulationRequest): Promise<SimulationRun>;
}
