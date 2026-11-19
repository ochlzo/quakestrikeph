import json

import pytest

from quakestrike.application.alerts import SmsSupportUnavailable
from quakestrike.infrastructure.sms.iprog import IprogSmsSupport


class Response:
    status_code = 200

    def __init__(self, body):
        self.body = body
        self.headers = {}

    def json(self):
        return self.body

    def iter_content(self, size):
        yield json.dumps(self.json()).encode()

    def close(self):
        pass


@pytest.mark.parametrize(
    ("network", "smart", "expected"),
    [
        ("Globe/TM", False, True),
        ("Globe", False, True),
        ("TM", False, True),
        ("DITO", False, True),
    ],
)
def test_ordinary_network_support_preserves_documented_coverage(network, smart, expected):
    calls = []

    def request(url, **options):
        calls.append((url, options))
        return Response({"status": "success", "data": {"network": network, "is_smart_tnt": smart}})

    assert IprogSmsSupport("secret", request=request).supported("+639171234567") is expected
    assert calls[0][0] == "https://www.iprogsms.com/api/v1/phone_numbers/detect"
    assert calls[0][1]["allow_redirects"] is False
    assert calls[0][1]["timeout"] == (3, 8)


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {"status": "error", "message": "secret"},
    ],
)
def test_failed_or_unrecognized_lookup_does_not_prove_unsupported(body):
    with pytest.raises(SmsSupportUnavailable) as failure:
        IprogSmsSupport("secret", request=lambda *a, **k: Response(body)).supported("+639171234567")
    assert "secret" not in str(failure.value)
    assert "+639" not in str(failure.value)


def test_missing_configuration_never_calls_provider():
    def request(*a, **k):
        pytest.fail("Provider must not be called.")

    with pytest.raises(SmsSupportUnavailable):
        IprogSmsSupport(None, request=request).supported("+639171234567")


def test_documented_invalid_format_excludes_sms_without_service_failure():
    body = {
        "status": "error",
        "data": {"network": "Invalid Format", "is_smart_tnt": False},
        "message": "Invalid phone number format. Philippine mobile numbers must be in format: "
        "09XXXXXXXXX or +639XXXXXXXXX (11 digits total)",
    }
    assert (
        IprogSmsSupport("secret", request=lambda *a, **k: Response(body)).supported("bad") is False
    )
