from types import SimpleNamespace
from uuid import uuid4

import pytest
import requests

from quakestrike.application.alert_delivery import AlertSubmission
from quakestrike.infrastructure.sms.iprog import IprogAlertProvider


def submission(body="QuakeStrike PH\n\nView current forecast https://example.test/forecasts/event"):
    return AlertSubmission(uuid4(), uuid4(), uuid4(), "sms", "+639171234567", body)


class Response:
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        return self.body


def test_ordinary_submission_preserves_frozen_content_and_accepts_numeric_status():
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response({"status": 200, "message_id": "iSms-accepted"})

    request = submission()
    result = IprogAlertProvider("secret", post=post).submit(request)
    assert result.status == "accepted"
    assert result.reference == "iSms-accepted"
    assert result.evidence["provider_code"] == 200
    assert result.evidence["http_status"] == 200
    assert calls == [
        (
            "https://www.iprogsms.com/api/v1/sms_messages",
            {
                "json": {
                    "api_token": "secret",
                    "phone_number": request.destination,
                    "message": request.body,
                },
                "timeout": (3, 8),
                "allow_redirects": False,
            },
        )
    ]


@pytest.mark.parametrize(
    "http,body,status,error,reference",
    [
        (
            200,
            {"status": 500, "message": "Invalid api token or no load balance"},
            "permanent",
            "provider_credentials_or_credit",
            None,
        ),
        (
            200,
            {"status": 500, "message": "API Token, phone number and message are required."},
            "permanent",
            "provider_permanent_rejection",
            None,
        ),
        (
            500,
            {"status": 500, "message": "upstream error secret"},
            "unknown",
            "provider_failure",
            None,
        ),
        (
            200,
            {"status": "success", "message_id": "known"},
            "unknown",
            "provider_invalid_response",
            "known",
        ),
        (200, {"status": 200}, "unknown", "provider_invalid_response", None),
        (
            200,
            {"status": True, "message_id": "known"},
            "unknown",
            "provider_invalid_response",
            "known",
        ),
        (200, [], "unknown", "provider_invalid_response", None),
        (200, {"status": 200, "message_id": " bad "}, "unknown", "provider_invalid_response", None),
        (503, {"status": 200, "message_id": "known"}, "unknown", "provider_failure", "known"),
        (429, {}, "transient", "provider_rate_limited", None),
        (429, {"status": 200, "message_id": "known"}, "unknown", "provider_failure", "known"),
        (401, {}, "permanent", "provider_credentials_or_credit", None),
        (302, {}, "unknown", "provider_failure", None),
    ],
)
def test_ordinary_errors_keep_http_and_body_evidence_separate(http, body, status, error, reference):
    provider = IprogAlertProvider("secret", post=lambda *a, **k: Response(body, http))
    result = provider.submit(submission())
    assert (result.status, result.error_code, result.reference) == (status, error, reference)
    assert result.evidence["http_status"] == http
    assert "secret" not in str(result)


def test_transport_uncertainty_and_malformed_json_never_retry_inside_adapter():
    calls = []

    def post(*a, **k):
        calls.append(True)
        raise requests.Timeout("secret token destination message")

    result = IprogAlertProvider("secret", post=post).submit(submission())
    assert result.status == "unknown"
    assert result.error_code == "provider_transport_uncertain"
    assert calls == [True]
    assert "secret" not in str(result)

    class Malformed(Response):
        def json(self):
            raise ValueError("raw secret response")

    result = IprogAlertProvider("secret", post=lambda *a, **k: Malformed(None)).submit(submission())
    assert result.status == "unknown"
    assert result.error_code == "provider_invalid_response"


def test_rate_limit_timing_and_safe_charging_metadata():
    result = IprogAlertProvider(
        "secret", post=lambda *a, **k: Response({}, 429, {"Retry-After": "75"})
    ).submit(submission())
    assert result.retry_after_seconds == 75
    assert result.evidence["retry_delay_seconds"] == 75
    result = IprogAlertProvider(
        "secret",
        post=lambda *a, **k: Response(
            {
                "status": 200,
                "message_id": "known",
                "sms_rate": 2.5,
                "sms_count": 3,
                "message_status_link": "https://evil.test/?api_token=secret",
                "phone": "secret",
            }
        ),
    ).submit(submission())
    assert result.evidence["charging_units"] == 2.5
    assert result.evidence["provider_sms_count"] == 3
    assert "secret" not in str(result)


@pytest.mark.parametrize(
    "body,encoding,segments",
    [
        ("a" * 160, "GSM-7", 1),
        ("a" * 161, "GSM-7", 2),
        ("a" * 306, "GSM-7", 2),
        ("a" * 307, "GSM-7", 3),
        ("^" * 80, "GSM-7", 1),
        ("^" * 81, "GSM-7", 2),
        ("é" * 160, "GSM-7", 1),
        ("漢" * 70, "Unicode", 1),
        ("漢" * 71, "Unicode", 2),
        ("漢" * 134, "Unicode", 2),
        ("😀" * 35, "Unicode", 1),
        ("😀" * 36, "Unicode", 2),
    ],
)
def test_submission_estimates_segments_without_modifying_text(body, encoding, segments):
    sent = []

    def post(*a, **k):
        sent.append(k["json"]["message"])
        return Response({"status": 200, "message_id": "known"})

    result = IprogAlertProvider("secret", post=post).submit(submission(body))
    assert result.evidence["encoding"] == encoding
    assert result.evidence["estimated_segments"] == segments
    assert sent == [body]


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {"status": 200, "message_status": []},
        {"status": 200, "message_status": {"secret": "value"}},
        {"status": "success", "message_status": "completed"},
        {"status": 200, "message_status": "completed", "message_id": "other"},
    ],
)
def test_malformed_poll_outcome_remains_unknown(body):
    outcome = IprogAlertProvider("secret", get=lambda *a, **k: Response(body)).poll("known")
    assert outcome.status == "unknown"
    assert "secret" not in str(outcome)


@pytest.mark.parametrize(
    "http,status,error",
    [
        (401, "permanent", "provider_credentials_or_credit"),
        (429, "transient", "provider_rate_limited"),
        (503, "unknown", "provider_failure"),
    ],
)
def test_http_rejection_remains_classified_without_json(http, status, error):
    class NonJson(Response):
        def json(self):
            raise ValueError("secret response")

    result = IprogAlertProvider("secret", post=lambda *a, **k: NonJson(None, http)).submit(
        submission()
    )
    assert (result.status, result.error_code) == (status, error)
    assert result.evidence["http_status"] == http


def test_polling_boundary_sanitizes_provider_evidence_before_reporting():
    from quakestrike.application.sms_polling import poll_iprog_deliveries

    candidate = SimpleNamespace(delivery_attempt_id=uuid4(), provider_message_id="known")

    class Store:
        def iprog_poll_candidates(self, **kwargs):
            return [candidate]

    class Provider:
        def poll(self, reference):
            return SimpleNamespace(
                status="unknown",
                error_code="raw secret prose",
                evidence={
                    "token": "secret",
                    "operation": "sms_status",
                    "http_status": 503,
                    "raw": "secret",
                },
            )

    reported = []
    poll_iprog_deliveries(Store(), Provider(), report=lambda c, r, o: reported.append(r))
    assert reported[0].error_code == "provider_failure"
    assert reported[0].evidence == {"operation": "sms_status", "http_status": 503}
    assert "secret" not in str(reported)
