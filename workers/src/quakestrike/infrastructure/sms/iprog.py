"""IPROG ordinary shared-sender support; no OTP or message submission calls."""

import requests

from quakestrike.application.alerts import SmsSupportUnavailable


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
