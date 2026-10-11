"""Recipient resolution with fenced storage and an independent SMS support port."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from quakestrike.domain.alerts import eligible_alert_channels


class SmsSupportUnavailable(Exception):
    """A support lookup failed without proving that a destination is unsupported."""

    def __init__(self, code: str = "sms_support_unavailable"):
        allowed = {
            "sms_support_configuration",
            "sms_support_http_failure",
            "sms_support_transport_or_response",
            "sms_support_provider_failure",
            "sms_support_malformed_response",
            "sms_support_unrecognized_network",
        }
        self.code = code if code in allowed else "sms_support_unavailable"
        super().__init__(self.code)


class AlertClaimLost(Exception):
    """The root processing lease no longer authorizes a write."""


class SmsSupport(Protocol):
    def supported(self, phone: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class AlertClaim:
    dispatch_id: UUID
    alert_job_id: UUID
    correlation_id: UUID
    token: UUID
    magnitude: float
    latitude: float
    longitude: float
    scan_through: UUID | None = None


@dataclass(frozen=True, slots=True)
class AlertResolutionResult:
    status: str
    claim: AlertClaim | None = None
    support_failures: tuple[str, ...] = ()


class AlertStore(Protocol):
    def claim(
        self, dispatch_id: UUID, alert_job_id: UUID, correlation_id: UUID
    ) -> AlertClaim | str: ...
    def candidate_page(
        self, claim: AlertClaim, after: UUID | None
    ) -> Sequence[Mapping[str, object]]: ...
    def renew(self, claim: AlertClaim) -> None: ...
    def record(self, claim: AlertClaim, recipients: Sequence[dict[str, object]]) -> None: ...
    def complete(self, claim: AlertClaim) -> bool: ...


class ResolveAlertRecipients:
    def __init__(self, store: AlertStore, sms_support: SmsSupport):
        self.store = store
        self.sms_support = sms_support

    def execute(
        self,
        dispatch_id: UUID,
        alert_job_id: UUID,
        correlation_id: UUID,
        *,
        clock=None,
        deadline=None,
    ) -> AlertResolutionResult:
        claim = self.store.claim(dispatch_id, alert_job_id, correlation_id)
        if isinstance(claim, str):
            return AlertResolutionResult(claim)
        support_failures = set()
        after = None
        try:
            while page := self.store.candidate_page(claim, after):
                recipients = []
                budget_exhausted = False
                for account in page:
                    if deadline is not None and clock() >= deadline - 30:
                        budget_exhausted = True
                        break
                    self.store.renew(claim)
                    for candidate in eligible_alert_channels(
                        account, claim.magnitude, claim.latitude, claim.longitude
                    ):
                        if candidate["channel"] in account.get("resolved_channels", ()):
                            continue
                        if candidate["channel"] == "sms":
                            if support_failures:
                                continue
                            try:
                                supported = self.sms_support.supported(candidate["destination"])
                            except SmsSupportUnavailable as error:
                                support_failures.add(error.code)
                                continue
                            if not supported:
                                continue
                            candidate["evidence"]["ordinary_sms_supported"] = True
                        recipients.append(candidate)
                self.store.record(claim, recipients)
                if budget_exhausted or (deadline is not None and clock() >= deadline - 30):
                    return AlertResolutionResult(
                        "incomplete", claim, tuple(sorted(support_failures))
                    )
                after = page[-1]["user_id"]
            if support_failures:
                return AlertResolutionResult("incomplete", claim, tuple(sorted(support_failures)))
            live = self.store.complete(claim)
            return AlertResolutionResult("resolved", claim if live else None)
        except AlertClaimLost:
            return AlertResolutionResult("stale")
