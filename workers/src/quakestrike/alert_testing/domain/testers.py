from math import isfinite
from uuid import UUID

from quakestrike.domain.alerts import alert_distance_km, eligible_alert_channels


def identity(value: object) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("A canonical UUID is required.")
    return value


def selection(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > 500:
        raise ValueError("Select at most 500 accounts.")
    result = [identity(item) for item in value]
    if len(set(result)) != len(result):
        raise ValueError("Account identities must be unique.")
    return result


def masked_destination(channel, value):
    value = value or ""
    if channel == "email":
        local, _, domain = value.partition("@")
        return f"{local[:1]}•••@{domain}" if domain else "Unavailable"
    return f"+63 ••• ••• {value[-4:]}" if value else "Unavailable"


def account_view(account, event: dict) -> dict:
    reason = ""
    try:
        magnitude, latitude, longitude = (
            float(event[key]) for key in ("magnitude", "latitude", "longitude")
        )
        if not all(isfinite(number) for number in (magnitude, latitude, longitude)) or not (
            1 <= magnitude <= 10 and -90 <= latitude <= 90 and -180 <= longitude <= 180
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        reason = "Enter a valid main magnitude and epicenter."
        magnitude = latitude = longitude = 0.0
    candidates = [] if reason else eligible_alert_channels(account, magnitude, latitude, longitude)
    eligible = {item["channel"] for item in candidates}
    if not reason:
        if account["account_status"] != "active":
            reason = "Account is not active."
        elif account["onboarding_completed_at"] is None:
            reason = "Onboarding is incomplete."
        elif magnitude < float(account["alert_trigger_magnitude"]):
            reason = f"Below M{account['alert_trigger_magnitude']:.1f} threshold."
        elif account["nearby_alerts_only"] and not candidates:
            lat, lon, limit = (
                account[key]
                for key in (
                    "alert_location_latitude",
                    "alert_location_longitude",
                    "alert_trigger_distance_km",
                )
            )
            if lat is None or lon is None or limit is None:
                reason = "Saved nearby settings are incomplete."
            elif alert_distance_km(latitude, longitude, float(lat), float(lon)) > float(limit):
                reason = f"Outside the {float(limit):g} km nearby limit."
    channels = {}
    for channel, destination, verified, enabled in (
        ("email", "email", "email_verified_at", "email_enabled"),
        ("sms", "mobile_number", "mobile_verified_at", "sms_enabled"),
    ):
        value = account[destination] or ""
        masked = masked_destination(channel, value)
        explanation = reason or (
            f"{channel.upper() if channel == 'sms' else 'Email'} disabled."
            if not account[enabled]
            else "Destination is not verified."
            if not value or account[verified] is None
            else ""
        )
        if not explanation:
            explanation = (
                "SMS sender support unknown." if channel == "sms" else "Provisionally eligible."
            )
        channels[channel] = {
            "destination": masked,
            "enabled": account[enabled],
            "verified": account[verified] is not None,
            "eligible": channel in eligible and channel == "email",
            "reason": explanation,
        }
    return {
        "id": str(account["user_id"]),
        "name": account["display_name"],
        "initials": "".join(word[:1] for word in account["display_name"].split()[:2]).upper(),
        "status": account["account_status"],
        "onboarding_complete": account["onboarding_completed_at"] is not None,
        "threshold": float(account["alert_trigger_magnitude"]),
        "nearby": account["nearby_alerts_only"],
        "limit": float(account["alert_trigger_distance_km"] or 0),
        "channels": channels,
    }
