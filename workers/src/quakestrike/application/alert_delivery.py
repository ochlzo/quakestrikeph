"""Channel submission over frozen content and durable attempt claims."""

import math
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

from quakestrike.application.alerts import AlertClaimLost, SmsSupportUnavailable


@dataclass(frozen=True, slots=True)
class AlertSubmission:
    attempt_id: UUID
    recipient_id: UUID
    token: UUID
    channel: str
    destination: str = field(repr=False)
    body: str = field(repr=False)
    subject: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    status: Literal["accepted", "transient", "permanent", "unknown"]
    reference: str | None = None
    error_code: str | None = None
    retry_after_seconds: float | None = None
    evidence: dict = field(default_factory=dict)


class AlertProvider(Protocol):
    def submit(self, request: AlertSubmission) -> SubmissionResult:
        """Make one bounded call, with no internal submission retry."""
        ...


def normalize_submission(result):
    """Retain only bounded normalized evidence from the external boundary."""
    status = getattr(result, "status", "unknown")
    reference = getattr(result, "reference", None)
    if reference is not None and (
        not isinstance(reference, str)
        or reference != reference.strip()
        or not 1 <= len(reference) <= 512
    ):
        return SubmissionResult("unknown", error_code="provider_invalid_response")
    if status not in ("accepted", "transient", "permanent", "unknown"):
        return SubmissionResult("unknown", error_code="provider_invalid_response")
    if status == "accepted" and reference is None:
        return SubmissionResult("unknown", error_code="provider_invalid_response")
    delay = getattr(result, "retry_after_seconds", None)
    if (
        not isinstance(delay, int | float)
        or isinstance(delay, bool)
        or not math.isfinite(delay)
        or delay < 0
    ):
        delay = None
    allowed_errors = {
        "provider_rejected",
        "provider_failure",
        "provider_rate_limited",
        "provider_credentials_or_credit",
        "provider_permanent_rejection",
        "provider_transport_uncertain",
        "provider_invalid_response",
    }
    error = getattr(result, "error_code", None)
    if error is not None and error not in allowed_errors:
        error = "provider_failure"
    evidence = {}
    raw = getattr(result, "evidence", {})
    if isinstance(raw, dict):
        for key in ("http_status", "estimated_segments", "charging_units"):
            value = raw.get(key)
            if (
                isinstance(value, int | float)
                and not isinstance(value, bool)
                and math.isfinite(value)
                and 0 <= value <= 1000000
            ):
                evidence[key] = value
        if raw.get("encoding") in ("GSM-7", "UCS-2", "Unicode"):
            evidence["encoding"] = raw["encoding"]
        if raw.get("operation") in ("submit", "sms_submit", "email_submit", "sms_status", "status"):
            evidence["operation"] = raw["operation"]
        if raw.get("error_category") in (
            "transient",
            "permanent",
            "unknown",
            "credentials_or_credit",
            "rate_limit",
        ):
            evidence["error_category"] = raw["error_category"]
        code = raw.get("provider_code")
        if isinstance(code, int) and not isinstance(code, bool) and 0 <= code <= 10000:
            evidence["provider_code"] = code
    return SubmissionResult(status, reference, error, delay, evidence)


def deliver_alert(claim, store, support, providers, *, clock, deadline, report, limit=100):
    """Drain a bounded roster using the resolver's live root claim."""
    try:
        for recipient in store.due_recipients(claim, limit):
            # Leave thirty seconds for the bounded provider call and durable settlement.
            if clock() >= deadline - 30:
                break
            store.renew_delivery(claim)
            supported = True
            if recipient.channel == "sms":
                try:
                    supported = support.supported(recipient.destination_snapshot)
                except SmsSupportUnavailable:
                    supported = None
            request = store.begin_submission(claim, recipient.recipient_id, supported)
            if request is None:
                continue
            if not store.allow_submission(claim, request):
                continue
            try:
                result = normalize_submission(providers[request.channel].submit(request))
            except Exception:
                result = SubmissionResult("unknown", error_code="provider_transport_uncertain")
            outcome = store.finish_submission(request, result)
            report(request, result, outcome)
        return store.finish_pass(claim)
    except AlertClaimLost:
        status = store.maintain(claim.dispatch_id, claim.alert_job_id, claim.correlation_id)
        return status if status in ("completed", "failed", "expired") else "stale"
