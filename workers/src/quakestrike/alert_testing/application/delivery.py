"""Only the isolated consumer invokes this workflow and its providers."""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from uuid import UUID, uuid4

from quakestrike.alert_testing.domain.testers import account_view, masked_destination
from quakestrike.application.alert_delivery import SubmissionResult, normalize_submission
from quakestrike.application.alerts import SmsSupportUnavailable
from quakestrike.domain.alerts import (
    AutomaticAlertCandidate,
    create_automatic_alert_snapshots,
    eligible_alert_channels,
)
from quakestrike.domain.prediction import ForecastOutput


@dataclass(frozen=True)
class TestSubmission:
    attempt_id: str
    destination: str = field(repr=False)
    body: str = field(repr=False)
    subject: str | None = field(default=None, repr=False)


def render_content(record, public_base_url, location_resolver):
    scenario = record["scenario"]
    event, values = scenario["event"], scenario["forecast"]

    def time(ms):
        return datetime.fromtimestamp(ms / 1000, UTC)

    job, revision, release = (
        UUID(record[key]) for key in ("forecast_id", "event_revision_id", "model_release_id")
    )
    forecast = ForecastOutput(
        time(values["window_start_ms"]),
        time(values["window_end_ms"]),
        values["p1"],
        values["p4"],
        values["p5"],
        values["count"],
        values["radius_km"],
        *(values["quantiles"] or [None, None, None]),
    )
    candidate = AutomaticAlertCandidate(
        job,
        release,
        release,
        revision,
        revision,
        job,
        "manual",
        False,
        Decimal(str(event["magnitude"])),
        time(event["event_time_ms"]),
        forecast.window_end,
        time(record["submitted_at_ms"]),
    )
    content = asdict(
        create_automatic_alert_snapshots(
            candidate,
            forecast=forecast,
            event_id=UUID(scenario["event_id"]),
            location_provenance=location_resolver(
                event["latitude"], event["longitude"], event["location"]
            ),
            public_base_url=public_base_url,
        )
    )
    url = f"{public_base_url}/forecasts/{scenario['event_id']}"
    for key in ("message", "email_body", "nearby_message", "nearby_email_body"):
        content[key] = content[key].replace(url, url + "?test=true")
    return content


class Delivery:
    def __init__(self, sessions, store, accounts, support, providers, location_resolver):
        self.sessions, self.store, self.accounts = sessions, store, accounts
        self.support, self.providers, self.location_resolver = support, providers, location_resolver

    def process(self, owner, event):
        record, job = self.store.load(owner, event)
        if record is None:
            return
        if "content" not in job:
            job = self.store.freeze(
                owner,
                event,
                render_content(
                    record, job["forecast_url"].split("/forecasts/", 1)[0], self.location_resolver
                ),
            )
        for user in job["selected"]:
            for channel in ("email", "sms"):
                self._channel(owner, event, user, channel, record, job)

    def _eligible(self, user, scenario):
        # Selected-only read; no account enumeration or writes during delivery.
        accounts = self.accounts.search("%", [user], 1, 5)["accounts"]
        account = accounts[0] if accounts else None
        event = scenario["event"]
        candidates = (
            eligible_alert_channels(
                account, event["magnitude"], event["latitude"], event["longitude"]
            )
            if account is not None
            else []
        )
        return account, {row["channel"]: row for row in candidates}

    def _channel(self, owner, event, user, channel, record, job):
        scenario = record["scenario"]
        account, candidates = self._eligible(user, scenario)
        candidate = candidates.get(channel)
        reason = (
            account_view(
                account,
                {
                    key: str(scenario["event"][key])
                    for key in ("magnitude", "latitude", "longitude")
                },
            )["channels"][channel]["reason"]
            if account is not None
            else "Account unavailable."
        )
        if channel == "sms" and candidate:
            try:
                supported = self.support.supported(candidate["destination"])
            except SmsSupportUnavailable:
                supported = None
            # Settings can change during the bounded support lookup.
            account, fresh = self._eligible(user, scenario)
            if supported is not True:
                candidate = None
                reason = "SMS sender support unknown." if supported is None else "SMS unsupported."
            elif fresh.get(channel, {}).get("destination") != candidate["destination"]:
                candidate = None
                reason = "SMS settings changed during support lookup."
            else:
                candidate = fresh[channel]
        session = self.sessions.read()
        if session.get("server_time_ms", 0) >= scenario["forecast"]["window_end_ms"]:
            candidate, reason = None, "Forecast expired."
        token = str(uuid4())
        row = {
            "token": token,
            "user_id": user,
            "channel": channel,
            "name": account["display_name"] if account is not None else "Unavailable account",
            "status": "unknown" if candidate else "skipped",
            "reason": "Provider call reserved; outcome not confirmed." if candidate else reason,
            "masked_destination": masked_destination(
                channel, account["email" if channel == "email" else "mobile_number"]
            )
            if account is not None
            else "Unavailable",
        }
        if candidate:
            nearby = candidate["evidence"]["nearby_alerts_only"]
            content = job["content"]
            prefix = "nearby_" if nearby else ""
            body = content[prefix + ("message" if channel == "sms" else "email_body")]
            subject = content[prefix + "email_subject"] if channel == "email" else None
            row.update(
                attempt_id=token,
                content_variant="nearby" if nearby else "general",
                eligibility=candidate["evidence"],
                destination=candidate["destination"],
                body=body,
                subject=subject,
            )
        reserved_at = monotonic()
        if not self.store.begin(owner, event, user, channel, row, call=bool(candidate)):
            return
        if not candidate:
            return
        if not self.store.allow(owner, event, row) or monotonic() - reserved_at >= 3:
            return
        request = TestSubmission(
            f"test:{owner}:{event}:{token}", row["destination"], row["body"], row["subject"]
        )
        try:
            result = normalize_submission(self.providers[channel].submit(request))
        except Exception:
            result = SubmissionResult("unknown", error_code="provider_transport_uncertain")
        row.update(
            status={"transient": "failed", "permanent": "failed"}.get(result.status, result.status),
            reason="Provider accepted the request; delivery is not confirmed."
            if result.status == "accepted"
            else "Provider outcome is unknown. No automatic resend."
            if result.status == "unknown"
            else "Provider rejected the request.",
            error_code=result.error_code,
            provider_reference=result.reference,
            provider_evidence=result.evidence,
        )
        self.store.finish(owner, event, row)
