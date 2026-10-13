export interface BrevoEvidence {
  attemptId: string | null;
  reference: string;
  status: 'accepted' | 'delivered' | 'failed';
  providerTime: string;
  errorCode: string | null;
}
export type ReconcileOutcome = 'applied' | 'ignored' | 'uncorrelated' | 'conflict';
export interface AlertReconciler { reconcile(evidence: BrevoEvidence): Promise<ReconcileOutcome> }
export interface TestBrevoEvidence extends BrevoEvidence {
  testSessionId: string;
  testEventId: string;
  attemptId: string;
}
export interface TestAlertReconciler { reconcile(evidence: TestBrevoEvidence): Promise<ReconcileOutcome> }
