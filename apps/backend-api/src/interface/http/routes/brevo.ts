import { createHash, timingSafeEqual } from 'node:crypto';
import express, { Router, type ErrorRequestHandler } from 'express';
import { brevoEvidence, InvalidBrevoCallback } from '../../../application/alerts/brevo.js';
import type { AlertReconciler } from '../../../ports/alertDelivery.js';

export interface BrevoDependencies { token?: string; reconciler: AlertReconciler }
export function brevoRoutes(dependencies: BrevoDependencies | undefined, now: () => Date) {
  const router = Router();
  router.use((req, res, next) => {
    const authorization = req.headers.authorization;
    if (!dependencies?.token || Object.keys(req.query).length !== 0 || typeof authorization !== 'string' || !/^Bearer [\x21-\x7e]{1,1024}$/.test(authorization) ||
      !timingSafeEqual(createHash('sha256').update(authorization.slice(7)).digest(),
        createHash('sha256').update(dependencies.token).digest())) { res.sendStatus(401); return; }
    if (!req.is('application/json')) { res.sendStatus(415); return; }
    next();
  });
  router.use(express.json({ limit: '32kb', strict: true, inflate: false }));
  router.post('/', async (req, res) => {
    const evidence = brevoEvidence(req.body, now());
    const outcome = await dependencies!.reconciler.reconcile(evidence);
    if (outcome === 'applied' || outcome === 'ignored') { res.sendStatus(204); return; }
    console.error(JSON.stringify({ service: 'backend-api', event: 'brevo_callback_unresolved', requestId: res.getHeader('X-Request-ID'), outcome }));
    if (outcome === 'conflict') { res.sendStatus(409); return; }
    res.setHeader('Retry-After', '60'); res.sendStatus(429);
  });
  const handleError: ErrorRequestHandler = (error: unknown, _req, res, _next) => {
    if (error instanceof InvalidBrevoCallback) { res.sendStatus(400); return; }
    const status = error && typeof error === 'object' && 'status' in error ? error.status : undefined;
    if (status === 400 || status === 413 || status === 415) { res.sendStatus(status); return; }
    console.error(JSON.stringify({ service: 'backend-api', event: 'brevo_callback_failed', requestId: res.getHeader('X-Request-ID'), category: 'processing_unavailable' }));
    res.setHeader('Retry-After', '60'); res.sendStatus(429);
  };
  router.use(handleError);
  return router;
}
