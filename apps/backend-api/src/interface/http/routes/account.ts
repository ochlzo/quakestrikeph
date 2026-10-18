import { Router, type ErrorRequestHandler } from 'express';
import type { AccountService } from '../../../application/accounts/service.js';
import { AccountError } from '../../../domain/accounts.js';
import type { AuthenticateAccount } from '../../../ports/accounts.js';

export interface AccountDependencies { service: AccountService; authenticate: AuthenticateAccount }
export function accountRoutes(dependencies?: AccountDependencies) {
  const router = Router();
  router.use(async (req, res, next) => {
    res.setHeader('Cache-Control', 'private, no-store');
    if (!dependencies) throw new AccountError('AUTH_UNAVAILABLE', 'Account access is temporarily unavailable.', 503);
    const headers = new Headers();
    if (req.headers.authorization) headers.set('authorization', req.headers.authorization);
    res.locals.identity = await dependencies.authenticate(headers);
    next();
  });
  const body = (value: unknown): Record<string, unknown> => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new AccountError('INVALID_REQUEST', 'Enter the required fields.');
    return value as Record<string, unknown>;
  };
  router.get('/', async (_req, res) => res.json(await dependencies!.service.read(res.locals.identity)));
  router.put('/profile', async (req, res) => res.json(await dependencies!.service.profile(res.locals.identity,
    body(req.body), String(res.getHeader('X-Request-ID')))));
  router.put('/preferences', async (req, res) => res.json(await dependencies!.service.save(res.locals.identity,
    req.body, String(res.getHeader('X-Request-ID')))));
  router.post('/phone/attempts', async (req, res) => res.status(201).json(await dependencies!.service.start(res.locals.identity,
    body(req.body), String(res.getHeader('X-Request-ID')))));
  router.post('/phone/verify', async (req, res) => res.json(await dependencies!.service.verify(res.locals.identity,
    body(req.body), String(res.getHeader('X-Request-ID')))));
  router.delete('/phone', async (_req, res) => res.json(await dependencies!.service.removePhone(res.locals.identity,
    String(res.getHeader('X-Request-ID')))));
  router.delete('/phone/attempts', async (_req, res) => {
    await dependencies!.service.cancel(res.locals.identity); res.sendStatus(204);
  });
  const denied: ErrorRequestHandler = async (error: unknown, _req, res, next) => {
    if (dependencies) await dependencies.service.failure(res.locals.identity,
      error instanceof AccountError ? error.code : 'ACCOUNT_REQUEST_FAILED', String(res.getHeader('X-Request-ID')));
    next(error);
  };
  router.use(denied);
  return router;
}
