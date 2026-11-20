"""Pure rules for creating automatic alert work from a completed forecast."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import asin, cos, floor, radians, sin, sqrt
from urllib.parse import urlsplit
from uuid import UUID

from quakestrike.domain.prediction import ForecastOutput

DEFAULT_PUBLIC_BULLETIN_BASE_URL = "https://quakestrikeph.com"


@dataclass(frozen=True, slots=True)
class AutomaticAlertCandidate:
    job_id: UUID
    job_release_id: UUID
    configured_release_id: UUID
    revision_id: UUID
    latest_revision_id: UUID
    latest_successful_job_id: UUID | None
    trigger_type: str
    event_superseded: bool
    magnitude: Decimal
    event_time: datetime
    window_end: datetime
    now: datetime
    historical_recovery: bool = False


@dataclass(frozen=True, slots=True)
class AutomaticAlertSnapshots:
    message: str
    recipient_policy: dict[str, object]
    email_subject: str
    email_body: str
    nearby_message: str
    nearby_email_subject: str
    nearby_email_body: str
    content_provenance: dict[str, object]


def create_automatic_alert_snapshots(
    candidate: AutomaticAlertCandidate,
    *,
    forecast: ForecastOutput | None = None,
    event_id: UUID | None = None,
    location_provenance: dict[str, object] | None = None,
    public_base_url: str = DEFAULT_PUBLIC_BULLETIN_BASE_URL,
) -> AutomaticAlertSnapshots | None:
    """Return fixed batch content only for a current, live, unexpired M1+ forecast."""

    if (
        candidate.job_release_id != candidate.configured_release_id
        or candidate.historical_recovery
        or candidate.event_superseded
        or candidate.latest_revision_id != candidate.revision_id
        or candidate.latest_successful_job_id != candidate.job_id
        or candidate.trigger_type not in {"scheduled", "manual"}
        or candidate.magnitude < 1
        or candidate.now >= candidate.window_end
    ):
        return None

    if forecast is None or event_id is None or location_provenance is None:
        raise ValueError(
            "A forecast alert needs complete forecast, event, and geographic evidence."
        )
    public_base_url = validate_public_bulletin_base_url(public_base_url)
    probability = forecast.probability_m1_plus_24h
    likelihood = "Low" if probability < 0.3 else "Medium" if probability < 0.7 else "High"
    link = f"View current forecast: {public_base_url}/forecasts/{event_id}"
    location = str(location_provenance["location_label"])
    common = (
        f"Location: {location}\n\n"
        f"Chance of further M1.0+ activity: {format_probability(probability)}\n"
        f"Likelihood: {likelihood}\n\n{link}"
    )
    general = f"M{candidate.magnitude:.1f} earthquake\n{common}"
    nearby = f"M{candidate.magnitude:.1f} earthquake near your saved alert location\n{common}"
    radius = (
        "Unavailable"
        if forecast.activity_radius_median_km_24h is None
        else f"{forecast.activity_radius_median_km_24h:g} km"
    )
    maximum_magnitude = (
        "Unavailable"
        if forecast.maximum_magnitude_q50_24h is None
        else f"M{forecast.maximum_magnitude_q50_24h:g}"
    )
    fuller = (
        f"\n\nExpected M1.0+ count: {forecast.expected_m1_plus_count_24h:g}\n"
        "Chance of further M4.0+ activity: "
        f"{format_probability(forecast.probability_m4_plus_24h)}\n"
        "Chance of further M5.0+ activity: "
        f"{format_probability(forecast.probability_m5_plus_24h)}\n"
        f"Possible further activity radius: {radius}\n"
        f"Possible maximum magnitude: {maximum_magnitude}\n\n"
        "The activity radius is not shaking distance or a safety boundary.\n"
        "These experimental estimates do not guarantee earthquake activity.\n"
        "The current forecast page may show a newer forecast than this frozen summary.\n"
        "Check PHIVOLCS for official updates."
    )
    return AutomaticAlertSnapshots(
        message=general,
        email_subject=f"QuakeStrike PH forecast after an M{candidate.magnitude:.1f} earthquake",
        email_body="QuakeStrike PH\n\n" + general + fuller,
        nearby_message=nearby,
        nearby_email_subject=(
            f"QuakeStrike PH forecast after an M{candidate.magnitude:.1f} earthquake "
            "near your saved alert location"
        ),
        nearby_email_body="QuakeStrike PH\n\n" + nearby + fuller,
        content_provenance={
            **location_provenance,
            "rendering_policy_version": "forecast-alert-v2",
        },
        recipient_policy={
            "version": "automatic_forecast_alert_v1",
            "observed_anchor_magnitude": float(candidate.magnitude),
            "account_status": "active",
            "onboarding_completed_required": True,
            "channels": ["sms", "email"],
            "verified_mobile_required": True,
            "sms_enabled_required": True,
            "verified_email_required": True,
            "email_enabled_required": True,
            "nearby_rule": "observed_epicenter_haversine_km <= user.alert_trigger_distance_km",
            "earth_radius_km": 6371.0088,
            "trigger_rule": "observed_anchor_magnitude >= user.alert_trigger_magnitude",
        },
    )


def format_probability(value: float) -> str:
    """Match Bulletin Math.round and its near-zero/near-one display rules."""
    if 0 < value < 0.005:
        return "<1%"
    if 0.995 <= value < 1:
        return ">99%"
    return f"{floor(value * 100 + 0.5)}%"


def validate_public_bulletin_base_url(value: str) -> str:
    parsed = urlsplit(value)
    # Accessing port validates numeric syntax and the URL port range.
    if parsed.port == 0:
        raise ValueError("The Bulletin URL port must be positive.")
    if (
        any(character.isspace() for character in value)
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"})
    ):
        raise ValueError(
            "The public Bulletin base URL must be an HTTPS origin or local HTTP origin."
        )
    return value.rstrip("/")


def alert_distance_km(
    latitude: float, longitude: float, other_latitude: float, other_longitude: float
) -> float:
    """Great-circle distance using the frozen recipient policy radius."""
    lat, other_lat = radians(latitude), radians(other_latitude)
    value = (
        sin((other_lat - lat) / 2) ** 2
        + cos(lat) * cos(other_lat) * sin(radians(other_longitude - longitude) / 2) ** 2
    )
    return 2 * 6371.0088 * asin(sqrt(min(1.0, max(0.0, value))))


def eligible_alert_channels(
    account, magnitude: float, latitude: float, longitude: float
) -> list[dict[str, object]]:
    """Evaluate current account settings without geographic display information."""
    threshold = account["alert_trigger_magnitude"]
    if (
        account["account_status"] != "active"
        or account["onboarding_completed_at"] is None
        or threshold is None
        or Decimal(str(magnitude)) < threshold
    ):
        return []
    nearby = account["nearby_alerts_only"]
    evidence = {
        "policy_version": "automatic_forecast_alert_v1",
        "account_status": "active",
        "onboarding_completed": True,
        "observed_magnitude": magnitude,
        "trigger_magnitude": float(threshold),
        "nearby_alerts_only": nearby,
    }
    if nearby:
        lat, lon = account["alert_location_latitude"], account["alert_location_longitude"]
        radius = account["alert_trigger_distance_km"]
        if lat is None or lon is None or radius is None:
            return []
        distance = alert_distance_km(latitude, longitude, float(lat), float(lon))
        if distance > float(radius):
            return []
        evidence.update(
            saved_latitude=float(lat),
            saved_longitude=float(lon),
            trigger_distance_km=float(radius),
            distance_km=distance,
            earth_radius_km=6371.0088,
        )
    candidates = []
    for channel, destination_key, verified_key, enabled_key in (
        ("email", "email", "email_verified_at", "email_enabled"),
        ("sms", "mobile_number", "mobile_verified_at", "sms_enabled"),
    ):
        destination = account[destination_key]
        verified = account[verified_key]
        if not account[enabled_key] or not destination or verified is None:
            continue
        candidates.append(
            {
                "user_id": account["user_id"],
                "channel": channel,
                "destination": destination.strip(),
                "evidence": {
                    **evidence,
                    "channel": channel,
                    "enabled": True,
                    "verified_at": verified.isoformat(),
                },
            }
        )
    return candidates
