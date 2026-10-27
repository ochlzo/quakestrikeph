import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import requests

from quakestrike.application.alert_delivery import AlertSubmission
from quakestrike.infrastructure.email.brevo import BrevoEmailProvider


class Response:
    status_code = 201

    def __init__(self):
        self.headers = {}

    def iter_content(self, size):
        yield json.dumps({"messageId": "<fixture@brevo>"}).encode()

    def close(self):
        pass


def submission():
    return AlertSubmission(
        uuid4(),
        uuid4(),
        uuid4(),
        "email",
        "reader@example.invalid",
        "Frozen body",
        "Frozen subject",
    )


@pytest.mark.parametrize(
    "http_status,body,expected,error",
    [
        (429, {"code": "too_many_requests"}, "transient", "provider_rate_limited"),
        (401, {"code": "unauthorized"}, "permanent", "provider_credentials_or_credit"),
        (402, {"code": "not_enough_credits"}, "permanent", "provider_credentials_or_credit"),
        (400, {"code": "invalid_parameter"}, "permanent", "provider_permanent_rejection"),
        (503, {"message": "PRIVATE"}, "unknown", "provider_failure"),
        (201, {}, "unknown", "provider_invalid_response"),
        (201, {"messageId": "\nPRIVATE"}, "unknown", "provider_invalid_response"),
        (201, {"messageId": " "}, "unknown", "provider_invalid_response"),
    ],
)
def test_email_response_classification_never_retries_uncertain_submissions(
    http_status, body, expected, error
):
    response = Response()
    response.status_code = http_status
    response.headers = {"Retry-After": "90"}
    response.iter_content = lambda size: iter([json.dumps(body).encode()])
    result = BrevoEmailProvider(
        "TEST_ONLY", "alerts@example.invalid", "QuakeStrike PH", request=lambda *a, **k: response
    ).submit(submission())
    assert result.status == expected
    assert result.error_code == error
    assert result.retry_after_seconds == (90 if http_status == 429 else None)
    assert "PRIVATE" not in repr(result)


def test_email_transport_failure_is_unknown_and_missing_configuration_never_calls():
    calls = []

    def post(*a, **k):
        calls.append(1)
        raise requests.Timeout("PRIVATE TOKEN")

    provider = BrevoEmailProvider(
        "TEST_ONLY", "alerts@example.invalid", "QuakeStrike PH", request=post
    )
    result = provider.submit(submission())
    assert result.status == "unknown"
    assert result.error_code == "provider_transport_uncertain"
    assert "PRIVATE" not in repr(result)
    assert len(calls) == 1
    provider.api_key = None
    assert provider.submit(submission()).status == "permanent"
    assert len(calls) == 1


def test_email_malformed_body_retains_http_evidence_without_provider_prose():
    response = Response()
    response.iter_content = lambda size: iter([b"PRIVATE NOT JSON"])
    result = BrevoEmailProvider(
        "TEST_ONLY", "alerts@example.invalid", "Fixture", request=lambda *a, **k: response
    ).submit(submission())
    assert result.status == "unknown"
    assert result.evidence == {"http_status": 201, "operation": "email_submit"}
    assert "PRIVATE" not in repr(result)


def test_email_stream_deadline_preserves_uncertainty_and_http_date_wait_is_not_shortened():
    times = iter((0, 13))
    provider = BrevoEmailProvider(
        "TEST_ONLY",
        "alerts@example.invalid",
        "Fixture",
        request=lambda *a, **k: Response(),
        clock=lambda: next(times, 13),
    )
    assert provider.submit(submission()).error_code == "provider_transport_uncertain"
    response = Response()
    response.status_code = 429
    response.headers = {"Retry-After": "Sun, 11 Oct 2026 00:01:30 GMT"}
    provider = BrevoEmailProvider(
        "TEST_ONLY",
        "alerts@example.invalid",
        "Fixture",
        request=lambda *a, **k: response,
        now=lambda: datetime(2026, 10, 11, tzinfo=UTC),
    )
    assert provider.submit(submission()).retry_after_seconds == 90


def test_invalid_sender_configuration_fails_before_request():
    def request(*a, **k):
        pytest.fail("Invalid configuration must not call provider")

    for key, email, name in [
        (" ", "alerts@example.invalid", "Fixture"),
        ("TEST_ONLY", "bad\naddress", "Fixture"),
        ("TEST_ONLY", "alerts@example.invalid", "\nPrivate"),
    ]:
        assert (
            BrevoEmailProvider(key, email, name, request=request).submit(submission()).status
            == "permanent"
        )


def test_email_html_preserves_frozen_text_without_interpreting_source_markup():
    calls = []

    def post(url, **options):
        calls.append(options["json"])
        return Response()

    request = replace(submission(), body="Observed <script> & location\nFrozen second line")
    assert (
        BrevoEmailProvider("TEST_ONLY", "alerts@example.invalid", "Fixture", request=post)
        .submit(request)
        .status
        == "accepted"
    )
    assert calls[0]["textContent"] == request.body
    assert (
        calls[0]["htmlContent"] == "<html><body><pre>Observed &lt;script&gt; &amp; location\n"
        "Frozen second line</pre></body></html>"
    )
