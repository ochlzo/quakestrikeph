import { randomUUID } from 'node:crypto';
import express, { type ErrorRequestHandler } from 'express';
import type { EarthquakeReader } from '../../ports/earthquakeReader.js';
import type { SyntheticScenarioReader } from '../../ports/syntheticScenarioReader.js';
import { DataUnavailable } from '../../application/information/errors.js';
import { InvalidRequest } from './searchRequest.js';
import { earthquakeRoutes } from './routes/earthquakes.js';
import { accountRoutes, type AccountDependencies } from './routes/account.js';
import { AccountError, SmsProviderError } from '../../domain/accounts.js';
import { accountErrorStatus } from './accountErrors.js';
import { brevoRoutes, type BrevoDependencies } from './routes/brevo.js';

export function createApp(reader: EarthquakeReader, now: () => Date = () => new Date(), accounts?: AccountDependencies,
  brevo?: BrevoDependencies, synthetic?: SyntheticScenarioReader) {
  const app = express();
  app.disable('x-powered-by');
  app.use((req, res, next) => {
    const requestId = randomUUID();
    res.setHeader('X-Request-ID', requestId);
    res.setHeader('X-Content-Type-Options', 'nosniff');
    const started = Date.now();
    res.on('finish', () => {
      console.info(JSON.stringify({ service: 'backend-api', requestId, method: req.method,
        route: req.route ? `${req.baseUrl}${req.route.path}` : 'unmatched',
        status: res.statusCode, durationMs: Date.now() - started }));
    });
    next();
  });

  app.use('/api/v1/callbacks/brevo', brevoRoutes(brevo, now));
  app.use((req, res, next) => {
    if (req.path.startsWith('/api/v1/earthquakes/') && req.query.test === 'true') res.setHeader('Cache-Control', 'no-store');
    next();
  });
  app.use(express.json({ limit: '8kb', strict: true }));

  app.get('/healthz', async (_req, res) => {
    await reader.check();
    res.json({ status: 'ready' });
  });

  app.use('/api/v1/earthquakes', earthquakeRoutes(reader, now, synthetic));
  app.use('/api/v1/account', accountRoutes(accounts));

  app.use((_req, res) => {
    res.status(404).json({ error: { code: 'NOT_FOUND', message: 'Route not found' } });
  });

  const handleError: ErrorRequestHandler = (error: unknown, _req, res, _next) => {
    if (error instanceof AccountError) {
      if (error instanceof SmsProviderError) console.error(JSON.stringify({ service: 'backend-api', event: 'sms_provider_failed',
        requestId: res.getHeader('X-Request-ID'), ...error.diagnostic }));
      res.status(accountErrorStatus(error)).json({ error: { code: error.code, message: error.message, ...(error.field ? { field: error.field } : {}) } });
      return;
    }
    if (error instanceof InvalidRequest) {
      res.status(400).json({ error: { code: 'INVALID_REQUEST', message: error.message } });
      return;
    }
    if (isBodyError(error)) {
      res.status(error.status === 413 ? 413 : 400).json({ error: {
        code: error.status === 413 ? 'PAYLOAD_TOO_LARGE' : 'INVALID_JSON',
        message: error.status === 413 ? 'Request body is too large' : 'Request body must be valid JSON',
      } });
      return;
    }
    const unavailable = isDatabaseError(error);
    console.error(JSON.stringify({ service: 'backend-api', requestId: res.getHeader('X-Request-ID'), event: 'request_failed',
      code: unavailable ? 'DATABASE_UNAVAILABLE' : 'INTERNAL_ERROR' }));
    res.status(unavailable ? 503 : 500).json({ error: {
      code: unavailable ? 'DATABASE_UNAVAILABLE' : 'INTERNAL_ERROR',
      message: unavailable ? 'Earthquake data is temporarily unavailable' : 'Internal server error',
    } });
  };
  app.use(handleError);
  return app;
}

function isBodyError(error: unknown): error is { status: number } {
  return !!error && typeof error === 'object' && 'type' in error && 'status' in error &&
    typeof error.status === 'number';
}

function isDatabaseError(error: unknown): boolean {
  if (error instanceof DataUnavailable) return true;
  if (!error || typeof error !== 'object' || !('code' in error)) return false;
  return ['ECONNREFUSED', 'ECONNRESET', 'ETIMEDOUT', 'ENOTFOUND', 'EAI_AGAIN',
    '57P01', '57P02', '57P03', '57014', '53300'].includes(String(error.code));
}
