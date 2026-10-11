"""One-recipient Brevo submission; acceptance does not establish delivery."""

import json
import math
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import escape
from time import monotonic

import requests

from quakestrike.application.alert_delivery import SubmissionResult


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
        if (
            not isinstance(self.api_key, str)
            or not re.fullmatch(r"[\x21-\x7e]{1,4096}", self.api_key)
            or not isinstance(self.sender_email, str)
            or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", self.sender_email)
            or not isinstance(self.sender_name, str)
            or not self.sender_name.strip()
            or len(self.sender_name) > 200
            or re.search(r"[\x00-\x1f\x7f]", self.sender_name)
        ):
            return SubmissionResult("permanent", error_code="provider_credentials_or_credit")
        deadline = self.clock() + 12
        try:
            response = self.request(
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
                timeout=(3, 8),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException:
            return SubmissionResult(
                "unknown",
                error_code="provider_transport_uncertain",
                evidence={"operation": "email_submit"},
            )
        try:
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
                            math.ceil((parsedate_to_datetime(retry) - self.now()).total_seconds()),
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
            chunks = bytearray()
            for chunk in response.iter_content(1):
                if self.clock() >= deadline:
                    return SubmissionResult(
                        "unknown", error_code="provider_transport_uncertain", evidence=evidence
                    )
                chunks.extend(chunk)
                if len(chunks) > 16384:
                    return SubmissionResult(
                        "unknown", error_code="provider_invalid_response", evidence=evidence
                    )
            body = json.loads(chunks)
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
                return SubmissionResult("unknown", error_code="provider_failure", evidence=evidence)
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
        finally:
            response.close()
