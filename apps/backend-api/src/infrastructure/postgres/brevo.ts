import type { Pool } from 'pg';
import type { AlertReconciler, BrevoEvidence, ReconcileOutcome } from '../../ports/alertDelivery.js';

export class PostgresBrevoReconciler implements AlertReconciler {
  constructor(private pool: Pool) {}
  async reconcile(evidence: BrevoEvidence): Promise<ReconcileOutcome> {
    const client = await this.pool.connect();
    let discard = false;
    try {
      await client.query('BEGIN');
      // Only this transaction invokes the approved write capability; role defaults remain read-only.
      await client.query('SET LOCAL transaction_read_only = off');
      const result = await client.query(`SELECT public.quakestrike_reconcile_brevo_delivery(
        $1::uuid, $2::text, $3::text, $4::timestamptz, $5::text) AS outcome`,
        [evidence.attemptId, evidence.reference, evidence.status, evidence.providerTime, evidence.errorCode]);
      const outcome: unknown = result.rows[0]?.outcome;
      if (typeof outcome !== 'string' || !['applied', 'ignored', 'uncorrelated', 'conflict'].includes(outcome)) {
        throw new Error('Invalid callback reconciliation result');
      }
      await client.query('COMMIT');
      return outcome as ReconcileOutcome;
    } catch (error) {
      try { await client.query('ROLLBACK'); } catch { discard = true; }
      throw error;
    } finally { client.release(discard); }
  }
}
