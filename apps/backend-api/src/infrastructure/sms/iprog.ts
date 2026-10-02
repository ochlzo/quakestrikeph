import { AccountError } from '../../domain/accounts.js';
import { createHmac, randomBytes } from 'node:crypto';
import type { PhoneProvider } from '../../ports/accounts.js';

export class Iprog implements PhoneProvider {
  private proofKey = randomBytes(32);
  constructor(private token: string | undefined, private request: typeof fetch = fetch) {}
  private async call(path: string, phone: string, extra: Record<string, unknown> = {}) {
    if (!this.token) throw new AccountError('SMS_UNAVAILABLE', 'Mobile verification is unavailable. You can save email preferences now.', 503);
    try {
      const response = await this.request(`https://www.iprogsms.com/api/v1/${path}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_token: this.token, phone_number: phone, ...extra }),
        signal: AbortSignal.timeout(8000), redirect: 'error',
      });
      if (!response.ok) throw new Error('provider unavailable');
      const result = await response.json() as Record<string, unknown>;
      return result;
    } catch {
      throw new AccountError('SMS_UNAVAILABLE', 'The SMS service did not respond. Please try again later.', 503);
    }
  }
  async supported(phone: string) {
    const result = await this.call('phone_numbers/detect', phone);
    const data = result.data as Record<string, unknown> | undefined;
    return result.status === 'success' && data?.is_smart_tnt === false &&
      typeof data.network === 'string' && ['globe', 'tm', 'globe/tm', 'dito'].includes(data.network.toLowerCase());
  }
  proof(attemptId: string, code: string) {
    return createHmac('sha256', this.proofKey).update(`${attemptId}:${code}`).digest('hex');
  }
  async send(phone: string, attemptId: string) {
    const result = await this.call('otp/send_otp', phone, { expires_in_minutes: 5 });
    // Never return, log or retain otp_code, message or the complete response.
    if (result.status !== 'success') throw new AccountError('SMS_UNAVAILABLE', 'A verification code could not be sent. Try again later.', 503);
    const data = result.data as Record<string, unknown> | undefined;
    if (typeof data?.otp_code !== 'string' || !/^\d{6}$/.test(data.otp_code)) {
      throw new AccountError('SMS_UNAVAILABLE', 'A verification code could not be confirmed. Request a new code later.', 503);
    }
    return this.proof(attemptId, data.otp_code);
  }
  async verify(phone: string, code: string) {
    return (await this.call('otp/verify_otp', phone, { otp: code })).status === 'success';
  }
}
