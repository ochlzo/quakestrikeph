"""Known-reference SMS evidence has no submission or account-write authority."""

from time import monotonic

from quakestrike.application.alert_delivery import SubmissionResult, normalize_submission
from quakestrike.application.sms_polling import SmsOutcome


class Reconciliation:
    def __init__(self, store, provider, report=lambda event, attempt, outcome: None):
        self.store, self.provider = store, provider
        self.report = report

    def once(self, owner):
        reserved_at = monotonic()
        candidate = self.store.poll_candidate(owner)
        if candidate is None or monotonic() - reserved_at >= 3:
            return False
        event, row = candidate
        try:
            raw = self.provider.poll(row["provider_reference"])
            status = getattr(raw, "status", "unknown")
            error = getattr(raw, "error_code", None)
            if status not in {"unknown", "accepted", "delivered", "failed"}:
                status, error = "unknown", "provider_invalid_response"
            safe = normalize_submission(
                SubmissionResult("unknown", error_code=error, evidence=getattr(raw, "evidence", {}))
            )
            outcome = SmsOutcome(status, safe.error_code, safe.evidence)
        except Exception:
            # The claim schedules a bounded later poll; uncertainty never permits a send.
            outcome = SmsOutcome("unknown", "provider_transport_uncertain")
        self.report(event, row["attempt_id"], outcome)
        if outcome.status == "unknown":
            return True
        self.store.reconcile_sms(owner, event, row, outcome)
        return True
