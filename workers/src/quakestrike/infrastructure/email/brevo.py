"""One-recipient Brevo submission; acceptance does not establish delivery."""

import math
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import escape
from time import monotonic

import requests

from quakestrike.application.alert_delivery import SubmissionResult
from quakestrike.infrastructure.provider_http import provider_json, provider_response


def valid_brevo_configuration(api_key, sender_email, sender_name):
    return bool(
        isinstance(api_key, str)
        and re.fullmatch(r"[\x21-\x7e]{1,4096}", api_key)
        and isinstance(sender_email, str)
        and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", sender_email)
        and isinstance(sender_name, str)
        and sender_name.strip()
        and len(sender_name) <= 200
        and not re.search(r"[\x00-\x1f\x7f]", sender_name)
    )


class BrevoEmailProvider:
    def __init__(
        self,
        api_key,
        sender_email,
        sender_name,
        *,
        request=requests.post,
        clock=monotonic,
        now=lambda: datetime.now(UTC),
    ):
        self.api_key = api_key
        self.sender_email = sender_email
        self.sender_name = sender_name
        self.request = request
        self.clock = clock
        self.now = now

    def submit(self, submission):
        if not valid_brevo_configuration(self.api_key, self.sender_email, self.sender_name):
            return SubmissionResult("permanent", error_code="provider_credentials_or_credit")
        evidence = {"operation": "email_submit"}
        try:
            with provider_response(
                self.request,
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": self.api_key, "Content-Type": "application/json"},
                json={
                    "sender": {"email": self.sender_email, "name": self.sender_name},
                    "to": [{"email": submission.destination}],
                    "subject": submission.subject,
                    "textContent": submission.body,
                    "htmlContent": (
                        f"<html><body><pre>{escape(submission.body)}</pre></body></html>"
                    ),
                    "headers": {"X-Mailin-custom": f"quakestrike-attempt:{submission.attempt_id}"},
                },
                clock=self.clock,
            ) as (response, deadline):
                evidence = {"http_status": response.status_code, "operation": "email_submit"}
                if response.status_code == 429:
                    retry = response.headers.get("Retry-After", "")
                    delay = int(retry) if re.fullmatch(r"[0-9]{1,128}", retry) else None
                    if delay is None and re.fullmatch(
                        r"[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT", retry
                    ):
                        try:
                            delay = max(
                                0,
                                math.ceil(
                                    (parsedate_to_datetime(retry) - self.now()).total_seconds()
                                ),
                            )
                        except (ValueError, OverflowError, TypeError):
                            pass
                    return SubmissionResult(
                        "transient",
                        error_code="provider_rate_limited",
                        retry_after_seconds=delay,
                        evidence=evidence,
                    )
                if response.status_code in (401, 403, 402):
                    return SubmissionResult(
                        "permanent", error_code="provider_credentials_or_credit", evidence=evidence
                    )
                body = provider_json(response, deadline, clock=self.clock)
                if (
                    response.status_code == 400
                    and isinstance(body, dict)
                    and body.get("code")
                    in {
                        "invalid_parameter",
                        "missing_parameter",
                        "invalid_email",
                        "not_enough_credits",
                        "unauthorized",
                    }
                ):
                    error = (
                        "provider_credentials_or_credit"
                        if body["code"] in {"not_enough_credits", "unauthorized"}
                        else "provider_permanent_rejection"
                    )
                    return SubmissionResult("permanent", error_code=error, evidence=evidence)
                if response.status_code != 201:
                    return SubmissionResult(
                        "unknown", error_code="provider_failure", evidence=evidence
                    )
                reference = body.get("messageId") if isinstance(body, dict) else None
                if (
                    not isinstance(reference, str)
                    or not 1 <= len(reference) <= 512
                    or re.search(r"[\x00-\x20\x7f]", reference)
                ):
                    return SubmissionResult(
                        "unknown", error_code="provider_invalid_response", evidence=evidence
                    )
                if reference.startswith("<") and reference.endswith(">"):
                    reference = reference[1:-1]
                if not reference or "<" in reference or ">" in reference:
                    return SubmissionResult(
                        "unknown", error_code="provider_invalid_response", evidence=evidence
                    )
                return SubmissionResult("accepted", reference=reference, evidence=evidence)
        except requests.RequestException:
            return SubmissionResult(
                "unknown", error_code="provider_transport_uncertain", evidence=evidence
            )
        except (ValueError, TypeError):
            return SubmissionResult(
                "unknown", error_code="provider_invalid_response", evidence=evidence
            )
