export interface BrevoEvidence {
  attemptId: string | null;
  reference: string;
  status: 'accepted' | 'delivered' | 'failed';
  providerTime: string;
  errorCode: string | null;
}
export type ReconcileOutcome = 'applied' | 'ignored' | 'uncorrelated' | 'conflict';
export interface AlertReconciler { reconcile(evidence: BrevoEvidence): Promise<ReconcileOutcome> }
