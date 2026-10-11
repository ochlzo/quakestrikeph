import { SmsProviderError, type SmsDiagnostic } from '../../domain/accounts.js';
import { createHmac, randomBytes } from 'node:crypto';
import type { PhoneProvider } from '../../ports/accounts.js';

function object(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

export class Iprog implements PhoneProvider {
  private proofKey = randomBytes(32);
  constructor(private token: string | undefined, private request: typeof fetch = fetch) {}
  private async call(operation: SmsDiagnostic['operation'], phone: string, extra: Record<string, unknown> = {}) {
    const diagnostic: SmsDiagnostic = { provider: 'iprog', operation, category: 'configuration',
      failureSource: 'configuration', providerCode: null, httpStatus: null, retryAfterSeconds: null };
    const fail = (category: SmsDiagnostic['category']): never => { throw new SmsProviderError({ ...diagnostic, category }); };
    if (!this.token?.trim()) return fail('configuration');
    let response: Response;
    try {
      const path = operation === 'detect' ? 'phone_numbers/detect' : `otp/${operation}`;
      response = await this.request(`https://www.iprogsms.com/api/v1/${path}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_token: this.token, phone_number: phone, ...extra }),
        signal: AbortSignal.timeout(8000), redirect: 'error',
      });
    } catch {
      diagnostic.failureSource = 'transport';
      return fail('transport_uncertain');
    }
    diagnostic.httpStatus = response.status;
    diagnostic.failureSource = response.ok ? 'body' : 'http';
    const retry = response.headers.get('retry-after');
    if (retry && /^\d{1,6}$/.test(retry)) diagnostic.retryAfterSeconds = Number(retry);
    else if (retry && /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT$/.test(retry)) {
      const delay = Math.max(0, Math.ceil((Date.parse(retry) - Date.now()) / 1000));
      if (Number.isFinite(delay) && delay <= 999999) diagnostic.retryAfterSeconds = delay;
    }
    let result: Record<string, unknown> | undefined;
    try { result = object(await response.json()); } catch (error) {
      if (response.ok && !(error instanceof SyntaxError)) {
        diagnostic.failureSource = 'transport';
        return fail('transport_uncertain');
      }
      // HTTP failures retain their status even when the body cannot be parsed.
    }
    // Only bounded numeric status codes enter diagnostics; provider text may contain secrets.
    if (typeof result?.status === 'number' && Number.isInteger(result.status) && result.status >= 400 && result.status <= 599) {
      diagnostic.providerCode = result.status;
    }
    if (response.status === 429 || diagnostic.providerCode === 429) return fail('rate_limit');
    if (result?.message === 'Invalid api token or no load balance') return fail('credential_or_credit');
    if (response.status === 401 || response.status === 403) return fail('credentials');
    if (response.status === 402) return fail('credits');
    if (!response.ok) return fail('http_failure');
    if (!result || (result.status !== 'success' && result.status !== 'error' && diagnostic.providerCode === null)) return fail('malformed_response');
    const data = object(result.data);
    if (operation === 'detect' && result.status === 'error' && data?.network === 'Invalid Format' && data.is_smart_tnt === false &&
      result.message === 'Invalid phone number format. Philippine mobile numbers must be in format: 09XXXXXXXXX or +639XXXXXXXXX (11 digits total)') return result;
    if (result.status !== 'success') return fail('provider_failure');
    if (operation === 'detect' && (!data || typeof data.network !== 'string' || typeof data.is_smart_tnt !== 'boolean')) return fail('malformed_response');
    if (operation === 'send_otp' && (typeof data?.otp_code !== 'string' || !/^\d{6}$/.test(data.otp_code))) return fail('malformed_response');
    return result;
  }
  async supported(phone: string) {
    const result = await this.call('detect', phone);
    const data = result.data as Record<string, unknown> | undefined;
    return result.status === 'success' && data?.is_smart_tnt === false &&
      typeof data.network === 'string' && ['globe', 'tm', 'globe/tm', 'dito'].includes(data.network.toLowerCase());
  }
  proof(attemptId: string, code: string) {
    return createHmac('sha256', this.proofKey).update(`${attemptId}:${code}`).digest('hex');
  }
  async send(phone: string, attemptId: string) {
    const result = await this.call('send_otp', phone, { expires_in_minutes: 5 });
    // Never return, log or retain otp_code, message or the complete response.
    const data = result.data as { otp_code: string };
    return this.proof(attemptId, data.otp_code);
  }
  async verify(phone: string, code: string) {
    // shortcut: IPROG does not document negative OTP results; fail closed until a verified mismatch contract exists.
    return (await this.call('verify_otp', phone, { otp: code })).status === 'success';
  }
}
