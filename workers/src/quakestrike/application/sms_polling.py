"""Bounded known-reference reconciliation without submission authority."""

from dataclasses import dataclass, field
from time import monotonic
from typing import Literal
from uuid import UUID

from quakestrike.application.alert_delivery import SubmissionResult, normalize_submission


@dataclass(frozen=True, slots=True)
class SmsOutcome:
    status: Literal["accepted", "delivered", "failed", "unknown"]
    error_code: str | None = None
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SmsPollPage:
    processed: int
    next_after: UUID | None


def poll_iprog_deliveries(
    store,
    provider,
    *,
    after=None,
    limit=20,
    clock=monotonic,
    deadline=None,
    report=lambda candidate, result, outcome: None,
):
    """The caller retains the cursor across passes and wraps after an exhausted page."""
    if not 1 <= limit <= 100:
        raise ValueError("SMS poll batch must contain 1 to 100 attempts.")
    deadline = clock() + 240 if deadline is None else deadline
    candidates = store.iprog_poll_candidates(after=after, limit=limit)
    processed = 0
    cursor = after
    for candidate in candidates:
        if clock() >= deadline - 12:
            return SmsPollPage(processed, cursor)
        try:
            raw = provider.poll(candidate.provider_message_id)
            status = getattr(raw, "status", "unknown")
            error = getattr(raw, "error_code", None)
            if status not in ("accepted", "delivered", "failed", "unknown"):
                status, error = "unknown", "provider_invalid_response"
            if error is not None and not isinstance(error, str):
                error = "provider_failure"
            safe = normalize_submission(
                SubmissionResult("unknown", error_code=error, evidence=getattr(raw, "evidence", {}))
            )
            result = SmsOutcome(status, safe.error_code, safe.evidence)
        except Exception:
            result = SmsOutcome("unknown", "provider_transport_uncertain")
        outcome = "ignored"
        if result.status in ("accepted", "delivered", "failed"):
            try:
                outcome = store.reconcile_delivery(
                    candidate.delivery_attempt_id,
                    candidate.provider_message_id,
                    result.status,
                    None,
                    result.error_code,
                    provider="iprog",
                    evidence=result.evidence,
                )
                store.maintain(
                    candidate.dispatch_id, candidate.alert_job_id, candidate.correlation_id
                )
            except Exception:
                # Retry the read during a later sweep; one locked row cannot starve others.
                outcome = "poll_reconciliation_unavailable"
        report(candidate, result, outcome)
        processed += 1
        cursor = candidate.delivery_attempt_id
    return SmsPollPage(processed, cursor if len(candidates) == limit else None)
