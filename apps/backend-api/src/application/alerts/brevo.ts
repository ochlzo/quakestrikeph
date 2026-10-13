import type { BrevoEvidence, TestBrevoEvidence } from '../../ports/alertDelivery.js';

export class InvalidBrevoCallback extends Error {}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const failures = ['hard_bounce', 'soft_bounce', 'blocked', 'error', 'invalid_email'];

export function brevoEvidence(body: unknown, now: Date): BrevoEvidence | TestBrevoEvidence {
  const invalid = (): never => { throw new InvalidBrevoCallback('Invalid callback evidence'); };
  if (!body || typeof body !== 'object' || Array.isArray(body)) return invalid();
  const value = body as Record<string, unknown>;
  if (typeof value.event !== 'string' || !['request', 'deferred', 'delivered', ...failures].includes(value.event)) return invalid();
  if (typeof value['message-id'] !== 'string' || !value['message-id'].trim() || value['message-id'].length > 512 ||
    /[\x00-\x20\x7f]/.test(value['message-id'])) return invalid();
  let reference = value['message-id'];
  if (reference.startsWith('<') && reference.endsWith('>')) reference = reference.slice(1, -1);
  if (!reference || /[<>]/.test(reference)) return invalid();
  const seconds = value.ts_event;
  if (typeof seconds !== 'number' || !Number.isSafeInteger(seconds) || seconds < 0 || seconds * 1000 > now.getTime() + 300000) return invalid();
  const date = new Date(seconds * 1000);
  if (!Number.isFinite(date.getTime())) return invalid();
  let attemptId: string | null = null;
  let testOwner: { testSessionId: string; testEventId: string } | undefined;
  const custom = value['X-Mailin-custom'];
  if (custom !== undefined) {
    const prefix = 'quakestrike-attempt:';
    if (typeof custom !== 'string' || !custom.startsWith(prefix)) return invalid();
    const marker = custom.slice(prefix.length);
    if (marker.startsWith('test:')) {
      const parts = marker.split(':');
      if (parts.length !== 4 || !parts.slice(1).every(part => uuid.test(part))) return invalid();
      testOwner = { testSessionId: parts[1]!.toLowerCase(), testEventId: parts[2]!.toLowerCase() };
      attemptId = parts[3]!.toLowerCase();
    } else {
      if (!uuid.test(marker)) return invalid();
      attemptId = marker.toLowerCase();
    }
  }
  const failed = failures.includes(value.event);
  return { ...(testOwner ? { ...testOwner, attemptId: attemptId! } : { attemptId }), reference, status: failed ? 'failed' : value.event === 'delivered' ? 'delivered' : 'accepted',
    providerTime: date.toISOString(), errorCode: failed ? `brevo_${value.event}` : null };
}
