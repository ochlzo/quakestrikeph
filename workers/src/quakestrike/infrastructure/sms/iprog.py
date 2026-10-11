"""IPROG ordinary shared-sender support; no OTP or message submission calls."""

import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import requests

from quakestrike.application.alert_delivery import SubmissionResult, normalize_submission
from quakestrike.application.alerts import SmsSupportUnavailable
from quakestrike.application.sms_polling import SmsOutcome

GSM_BASIC = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./"
    "0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM_EXTENSION = frozenset("\f^{}\\[~]|€")


def _segment_evidence(body):
    if all(character in GSM_BASIC or character in GSM_EXTENSION for character in body):
        units = sum(2 if character in GSM_EXTENSION else 1 for character in body)
        encoding, single, multipart = "GSM-7", 160, 153
    else:
        units = sum(2 if ord(character) > 0xFFFF else 1 for character in body)
        encoding, single, multipart = "Unicode", 70, 67
    return {
        "encoding": encoding,
        "estimated_segments": 1 if units <= single else math.ceil(units / multipart),
    }


def _charging_evidence(body):
    evidence = {}
    credits = body.get("sms_rate")
    if type(credits) in (int, float) and math.isfinite(credits) and 0 <= credits <= 1000000:
        evidence["charging_units"] = credits
    count = body.get("sms_count")
    if type(count) is int and 0 <= count <= 1000000:
        evidence["provider_sms_count"] = count
    return evidence


class IprogSmsSupport:
    def __init__(self, token: str | None, *, request=requests.post):
        self.token = token
        self.request = request

    def supported(self, phone: str) -> bool:
        if not self.token or not self.token.strip():
            raise SmsSupportUnavailable("sms_support_configuration")
        try:
            response = self.request(
                "https://www.iprogsms.com/api/v1/phone_numbers/detect",
                json={"api_token": self.token, "phone_number": phone},
                timeout=(3, 8),
                allow_redirects=False,
            )
            if response.status_code != 200:
                raise SmsSupportUnavailable("sms_support_http_failure")
            body = response.json()
        except (requests.RequestException, ValueError):
            raise SmsSupportUnavailable("sms_support_transport_or_response") from None
        if isinstance(body, dict) and body.get("status") == "error":
            data = body.get("data")
            if (
                isinstance(data, dict)
                and data.get("network") == "Invalid Format"
                and data.get("is_smart_tnt") is False
                and body.get("message")
                == "Invalid phone number format. Philippine mobile "
                "numbers must be in format: 09XXXXXXXXX or +639XXXXXXXXX (11 digits total)"
            ):
                return False
        if not isinstance(body, dict) or body.get("status") != "success":
            raise SmsSupportUnavailable("sms_support_provider_failure")
        data = body.get("data")
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("network"), str)
            or type(data.get("is_smart_tnt")) is not bool
        ):
            raise SmsSupportUnavailable("sms_support_malformed_response")
        network = data["network"].lower()
        if data["is_smart_tnt"] is True and network in {"smart", "tnt", "smart/tnt"}:
            return False
        if data["is_smart_tnt"] is False and network in {"globe", "tm", "globe/tm", "dito"}:
            return True
        raise SmsSupportUnavailable("sms_support_unrecognized_network")


class IprogAlertProvider:
    """One ordinary submission; acceptance never establishes handset delivery."""

    def __init__(
        self,
        token: str | None,
        *,
        post=requests.post,
        get=requests.get,
        clock=lambda: datetime.now(UTC),
    ):
        self.token = token
        self.post = post
        self.get = get
        self.clock = clock

    def submit(self, request):
        evidence = {"operation": "sms_submit", **_segment_evidence(request.body)}
        if not self.token or not self.token.strip():
            return SubmissionResult(
                "permanent", error_code="provider_credentials_or_credit", evidence=evidence
            )
        try:
            response = self.post(
                "https://www.iprogsms.com/api/v1/sms_messages",
                json={
                    "api_token": self.token,
                    "phone_number": request.destination,
                    "message": request.body,
                },
                timeout=(3, 8),
                allow_redirects=False,
            )
        except requests.RequestException:
            return SubmissionResult(
                "unknown", error_code="provider_transport_uncertain", evidence=evidence
            )
        evidence["http_status"] = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        code = body.get("status")
        if type(code) is int:
            evidence["provider_code"] = code
        reference = body.get("message_id")
        if (
            not isinstance(reference, str)
            or reference != reference.strip()
            or not 1 <= len(reference) <= 512
        ):
            reference = None
        evidence.update(_charging_evidence(body))
        http = response.status_code
        status, error, delay = "unknown", "provider_invalid_response", None
        if reference is not None and (http != 200 or type(code) is not int or code != 200):
            error = "provider_failure" if http != 200 else "provider_invalid_response"
        elif http == 429:
            status, error = "transient", "provider_rate_limited"
            delay = self._retry_delay(response.headers.get("Retry-After"))
        elif http in (401, 403):
            status, error = "permanent", "provider_credentials_or_credit"
        elif http in (400, 404, 422):
            status, error = "permanent", "provider_permanent_rejection"
        elif http != 200:
            error = "provider_failure"
        elif type(code) is int and code == 200 and reference is not None:
            status, error = "accepted", None
        elif type(code) is int and code == 500:
            if body.get("message") == "Invalid api token or no load balance":
                status, error = "permanent", "provider_credentials_or_credit"
            elif body.get("message") == "API Token, phone number and message are required.":
                status, error = "permanent", "provider_permanent_rejection"
            else:
                error = "provider_failure"
        if error:
            evidence["error_category"] = (
                "credentials_or_credit"
                if error == "provider_credentials_or_credit"
                else "rate_limit"
                if status == "transient"
                else status
            )
        return normalize_submission(SubmissionResult(status, reference, error, delay, evidence))

    def _retry_delay(self, value):
        if not isinstance(value, str) or len(value) > 100:
            return None
        try:
            if value.isascii() and value.isdigit():
                return float(value)
            date = parsedate_to_datetime(value)
            if date.tzinfo is not None:
                return max(0, (date - self.clock()).total_seconds())
        except (ValueError, TypeError, OverflowError):
            pass
        return None

    def poll(self, reference):
        evidence = {"operation": "sms_status"}
        if not self.token or not self.token.strip():
            return SmsOutcome("unknown", "provider_credentials_or_credit", evidence)
        if (
            not isinstance(reference, str)
            or reference != reference.strip()
            or not 1 <= len(reference) <= 512
        ):
            return SmsOutcome("unknown", "provider_invalid_response", evidence)
        try:
            response = self.get(
                "https://www.iprogsms.com/api/v1/sms_messages/status",
                params={"api_token": self.token, "message_id": reference},
                timeout=(3, 8),
                allow_redirects=False,
            )
        except requests.RequestException:
            return SmsOutcome("unknown", "provider_transport_uncertain", evidence)
        evidence["http_status"] = response.status_code
        try:
            body = response.json()
        except ValueError:
            return SmsOutcome("unknown", "provider_invalid_response", evidence)
        if not isinstance(body, dict):
            return SmsOutcome("unknown", "provider_invalid_response", evidence)
        code = body.get("status")
        if type(code) is int:
            evidence["provider_code"] = code
        evidence.update(_charging_evidence(body))
        evidence = normalize_submission(SubmissionResult("unknown", evidence=evidence)).evidence
        if response.status_code != 200 or type(code) is not int or code != 200:
            return SmsOutcome("unknown", "provider_failure", evidence)
        if body.get("message_id", reference) != reference:
            return SmsOutcome("unknown", "provider_invalid_response", evidence)
        value = body.get("message_status")
        status = (
            {"pending": "accepted", "completed": "delivered", "failed": "failed"}.get(value)
            if isinstance(value, str)
            else None
        )
        if status is None:
            return SmsOutcome("unknown", "provider_invalid_response", evidence)
        return SmsOutcome(status, "provider_rejected" if status == "failed" else None, evidence)
