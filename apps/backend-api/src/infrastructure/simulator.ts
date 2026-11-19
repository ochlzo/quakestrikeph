import type { ForecastSimulator, SimulationCatalog, SimulationRequest, SimulationRun } from '../application/forecastSimulations.js';

const unavailable: SimulationCatalog = { status: 'unavailable', catalogCutoff: null };

export class HttpForecastSimulator implements ForecastSimulator {
  constructor(private readonly baseUrl: URL, private readonly token: string) {}

  async catalog(): Promise<SimulationCatalog> {
    try {
      const response = await this.request('/catalog', 5_000);
      if (!response.ok) return unavailable;
      const status = await response.json() as SimulationCatalog;
      return status;
    } catch {
      return unavailable;
    }
  }

  async run(request: SimulationRequest): Promise<SimulationRun> {
    try {
      const response = await this.request('/run', 75_000, request);
      const body: unknown = await response.json();
      switch (response.status) {
        case 200: return { status: 200, body: body as Extract<SimulationRun, { status: 200 }>['body'] };
        case 429: {
          const retryAfter = response.headers.get('Retry-After');
          if (retryAfter === null || !/^\d+$/.test(retryAfter)) break;
          return { status: 429, retryAfter: Number(retryAfter), body: body as Extract<SimulationRun, { status: 429 }>['body'] };
        }
        case 500: case 503: case 504:
          return { status: response.status, body: body as Extract<SimulationRun, { status: 500 | 503 | 504 }>['body'] };
      }
    } catch (error) {
      const cause = error instanceof Error ? error.cause : undefined;
      if (cause && typeof cause === 'object' && 'code' in cause &&
        ['ECONNREFUSED', 'ENOTFOUND', 'EAI_AGAIN'].includes(String(cause.code))) {
        return { status: 503, body: { error: { code: 'SIMULATION_CATALOG_UNAVAILABLE', message: 'The PHIVOLCS catalog could not be checked.' } } };
      }
    }
    return { status: 504, body: { error: { code: 'SIMULATION_OUTCOME_UNKNOWN', message: 'The run timed out before its outcome could be confirmed.' } } };
  }

  private request(path: string, timeoutMs: number, body?: SimulationRequest) {
    return fetch(new URL(path, this.baseUrl), {
      method: body ? 'POST' : 'GET',
      headers: { Authorization: `Bearer ${this.token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(timeoutMs),
      redirect: 'error',
    });
  }
}
