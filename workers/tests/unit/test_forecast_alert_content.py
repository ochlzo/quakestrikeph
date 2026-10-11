from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from quakestrike.domain.alerts import AutomaticAlertCandidate, create_automatic_alert_snapshots
from quakestrike.domain.prediction import ForecastOutput


@pytest.fixture
def forecast_alert():
    event_time = datetime(2026, 10, 11, 4, tzinfo=UTC)
    job_id, release_id, revision_id = uuid4(), uuid4(), uuid4()
    candidate = AutomaticAlertCandidate(
        job_id=job_id,
        job_release_id=release_id,
        configured_release_id=release_id,
        revision_id=revision_id,
        latest_revision_id=revision_id,
        latest_successful_job_id=job_id,
        trigger_type="scheduled",
        event_superseded=False,
        magnitude=Decimal("4.2"),
        event_time=event_time,
        window_end=event_time + timedelta(hours=24),
        now=event_time + timedelta(hours=1),
    )
    forecast = ForecastOutput(
        window_start=event_time,
        window_end=candidate.window_end,
        probability_m1_plus_24h=0.7,
        probability_m4_plus_24h=0.2,
        probability_m5_plus_24h=0.1,
        expected_m1_plus_count_24h=3,
        activity_radius_median_km_24h=42,
        maximum_magnitude_q05_24h=1.3,
        maximum_magnitude_q50_24h=2.6,
        maximum_magnitude_q95_24h=5.7,
    )
    return candidate, forecast


@pytest.mark.parametrize("available", [True, False])
def test_alert_snapshots_use_amended_channel_copy(forecast_alert, available):
    candidate, forecast = forecast_alert
    if not available:
        forecast = replace(
            forecast,
            activity_radius_median_km_24h=None,
            maximum_magnitude_q05_24h=None,
            maximum_magnitude_q50_24h=None,
            maximum_magnitude_q95_24h=None,
        )
    snapshots = create_automatic_alert_snapshots(
        candidate,
        forecast=forecast,
        event_id=UUID("12345678-1234-5678-1234-567812345678"),
        location_provenance={"location_label": "near Davao Occidental"},
    )
    assert snapshots is not None
    for message in (snapshots.message, snapshots.nearby_message):
        assert message.startswith("M4.2 earthquake")
        assert "QuakeStrike PH" not in message
        assert "Possible further activity radius:" not in message
        assert "Possible maximum magnitude:" not in message
    for body in (snapshots.email_body, snapshots.nearby_email_body):
        assert body.startswith("QuakeStrike PH\n\nM4.2 earthquake")
        assert (
            "Possible further activity radius: 42 km\n"
            if available
            else "Possible further activity radius: Unavailable\n"
        ) in body
        assert (
            "Possible maximum magnitude: M2.6\n"
            if available
            else "Possible maximum magnitude: Unavailable\n"
        ) in body
        assert "M1.3" not in body and "M5.7" not in body
        assert "not shaking distance or a safety boundary" in body
    assert snapshots.email_subject.startswith("QuakeStrike PH forecast")
    assert snapshots.nearby_email_subject.startswith("QuakeStrike PH forecast")
    for body in (
        snapshots.message,
        snapshots.nearby_message,
        snapshots.email_body,
        snapshots.nearby_email_body,
    ):
        assert "Original 24-hour forecast window:" not in body
        assert "2026-10-11 12:00:00" not in body
        assert "Median activity radius:" not in body
        assert "Maximum magnitude (5th / 50th / 95th percentiles):" not in body
        assert "Chance of further M1.0+ activity: 70%\nLikelihood: High\n" in body
        assert (
            "View current forecast: https://quakestrikeph.qzz.io/forecasts/"
            "12345678-1234-5678-1234-567812345678"
        ) in body
    assert "near your saved alert location" in snapshots.nearby_message
    assert "near your saved alert location" in snapshots.nearby_email_body
    assert snapshots.content_provenance["rendering_policy_version"] == "forecast-alert-v2"


@pytest.mark.parametrize("offset,creates_alert", [(-1, True), (0, False), (1, False)])
def test_hidden_window_still_stops_alert_creation_at_original_expiry(
    forecast_alert, offset, creates_alert
):
    candidate, forecast = forecast_alert
    candidate = replace(candidate, now=candidate.window_end + timedelta(microseconds=offset))
    snapshots = create_automatic_alert_snapshots(
        candidate,
        forecast=forecast,
        event_id=uuid4(),
        location_provenance={"location_label": "near Davao Occidental"},
    )
    assert (snapshots is not None) == creates_alert
    assert forecast.window_end == datetime(2026, 10, 12, 4, tzinfo=UTC)
    assert forecast.maximum_magnitude_q05_24h == 1.3
    assert forecast.maximum_magnitude_q50_24h == 2.6
    assert forecast.maximum_magnitude_q95_24h == 5.7
