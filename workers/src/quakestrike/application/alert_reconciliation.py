"""Independent bounded polling and batch settlement with process-owned cursors."""

from time import monotonic

from quakestrike.application.sms_polling import poll_iprog_deliveries


class AlertReconciliation:
    def __init__(self, store, provider, *, clock=monotonic, report=lambda *args: None):
        self.store, self.provider = store, provider
        self.clock, self.report = clock, report
        self.poll_after = self.maintenance_after = None

    def execute(self, *, limit=20, poll_seconds=30, maintenance_seconds=5):
        if not 1 <= limit <= 100 or poll_seconds < 13 or maintenance_seconds <= 0:
            raise ValueError("Reconciliation phase bounds are invalid.")
        healthy, polled, maintained = True, 0, 0

        def report(candidate, result, outcome):
            nonlocal healthy
            if outcome == "poll_reconciliation_unavailable":
                healthy = False
            self.report(candidate, result, outcome)

        try:
            page = poll_iprog_deliveries(
                self.store,
                self.provider,
                after=self.poll_after,
                limit=limit,
                clock=self.clock,
                deadline=self.clock() + poll_seconds,
                report=report,
            )
            self.poll_after, polled = page.next_after, page.processed
        except Exception:
            healthy = False
            self.report(None, None, "poll_scan_unavailable")
        # The maintenance budget starts after polling, never from its deadline.
        deadline = self.clock() + maintenance_seconds
        try:
            candidates = self.store.maintenance_candidates(
                after=self.maintenance_after, limit=limit
            )
            completed_page = True
            for candidate in candidates:
                if self.clock() >= deadline:
                    completed_page = False
                    break
                try:
                    self.store.maintain(
                        candidate.dispatch_id, candidate.alert_job_id, candidate.correlation_id
                    )
                    maintained += 1
                except Exception:
                    healthy = False
                    self.report(None, None, "maintenance_unavailable")
                self.maintenance_after = candidate.alert_job_id
            if completed_page and len(candidates) < limit:
                self.maintenance_after = None
        except Exception:
            healthy = False
            self.report(None, None, "maintenance_scan_unavailable")
        return {"healthy": healthy, "polled": polled, "maintained": maintained}
