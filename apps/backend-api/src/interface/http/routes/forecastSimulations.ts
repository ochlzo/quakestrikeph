import { timingSafeEqual } from 'node:crypto';
import { isIP } from 'node:net';
import { Router, type Request } from 'express';
import {
  guestCookieLifetimeMs, guestCookieName, InvalidSimulationScenario, simulationScenario,
  type ForecastSimulator, type SimulationGuestCookies,
} from '../../../application/forecastSimulations.js';

export interface SimulationDependencies {
  simulator: ForecastSimulator;
  cookies: SimulationGuestCookies;
  pageToken: string;
  ingressKey?: string;
  localIngress?: boolean;
}

export function forecastSimulationRoutes(dependencies: SimulationDependencies, now: () => Date) {
  const router = Router();
  router.get('/internal/forecast-simulations/page', async (req, res) => {
    res.setHeader('Cache-Control', 'no-store');
    if (!matchesSecret(req.get('Authorization'), `Bearer ${dependencies.pageToken}`)) {
      res.status(404).json({ error: { code: 'NOT_FOUND', message: 'Route not found' } });
      return;
    }
    const guestCookieConfirmed = !!dependencies.cookies.identify(req.get('Cookie'), now());
    const catalog = await dependencies.simulator.catalog();
    if (!guestCookieConfirmed && req.query.confirm !== '1') {
      res.cookie(guestCookieName, dependencies.cookies.issue(now()), {
        path: '/', httpOnly: true, secure: true, sameSite: 'lax', maxAge: guestCookieLifetimeMs,
      });
    }
    res.json({ guestCookieConfirmed, catalog });
  });

  router.post('/api/v1/forecast-simulations', async (req, res) => {
    const guestId = dependencies.cookies.identify(req.get('Cookie'), now());
    if (!guestId) {
      res.status(403).json({ error: { code: 'SIMULATION_GUEST_COOKIE_REQUIRED', message: 'Confirm the guest cookie before running a simulation.' } });
      return;
    }
    let scenario;
    try {
      scenario = simulationScenario(req.body);
    } catch (error) {
      if (!(error instanceof InvalidSimulationScenario)) throw error;
      res.status(400).json({ error: { code: 'INVALID_REQUEST', message: error.message,
        ...(error.field ? { field: error.field } : {}) } });
      return;
    }
    const clientIp = simulationClientIp(req, dependencies);
    if (!clientIp) {
      res.status(503).json({ error: { code: 'SIMULATION_QUOTA_UNAVAILABLE', message: 'Simulation limits could not be checked.' } });
      return;
    }
    const run = await dependencies.simulator.run({ scenario, guestId, clientIp });
    if (run.status === 429) res.setHeader('Retry-After', run.retryAfter);
    res.status(run.status).json(run.body);
  });
  return router;
}

function simulationClientIp(req: Request, dependencies: SimulationDependencies): string | undefined {
  if (dependencies.localIngress) return req.socket.remoteAddress;
  if (!dependencies.ingressKey || !matchesSecret(req.get('X-Simulation-Ingress'), dependencies.ingressKey)) return undefined;
  const visitorIp = req.get('CF-Connecting-IP');
  return visitorIp && isIP(visitorIp) ? visitorIp : undefined;
}

function matchesSecret(supplied: string | undefined, expected: string): boolean {
  const actualBytes = Buffer.from(supplied ?? '');
  const expectedBytes = Buffer.from(expected);
  return actualBytes.length === expectedBytes.length && timingSafeEqual(actualBytes, expectedBytes);
}
