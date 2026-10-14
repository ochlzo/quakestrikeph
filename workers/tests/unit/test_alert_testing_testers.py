from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quakestrike.alert_testing.domain.testers import account_view


def profile(**changes):
    result = dict(
        user_id=uuid4(),
        display_name="Test Reader",
        account_status="active",
        onboarding_completed_at=datetime.now(UTC),
        alert_trigger_magnitude=Decimal("4.5"),
        nearby_alerts_only=False,
        alert_location_latitude=Decimal("9.86"),
        alert_location_longitude=Decimal("125.55"),
        alert_trigger_distance_km=Decimal("50"),
        email="private@example.invalid",
        email_verified_at=datetime.now(UTC),
        email_enabled=True,
        mobile_number="+639171234567",
        mobile_verified_at=datetime.now(UTC),
        sms_enabled=True,
    )
    return result | changes


def test_provisional_channels_use_saved_preferences_and_unknown_sms_support():
    event = {"magnitude": "4.5", "latitude": "9.86", "longitude": "125.55"}
    response = account_view(profile(), event)
    assert response["channels"]["email"]["eligible"]
    assert not response["channels"]["sms"]["eligible"]
    assert response["channels"]["sms"]["reason"] == "SMS sender support unknown."
    assert response["channels"]["email"]["destination"] == "p\u2022\u2022\u2022@example.invalid"
    assert "+639171234567" not in str(response)
    assert "alert_location_latitude" not in response
    assert not account_view(profile(email_enabled=False), event)["channels"]["email"]["eligible"]
    assert not account_view(profile(email_verified_at=None), event)["channels"]["email"]["eligible"]


@pytest.mark.parametrize(
    "changes,event,reason",
    [
        ({"account_status": "suspended"}, {}, "valid main magnitude"),
        (
            {"account_status": "suspended"},
            {"magnitude": "5.2", "latitude": "9.86", "longitude": "125.55"},
            "not active",
        ),
        (
            {"onboarding_completed_at": None},
            {"magnitude": "5.2", "latitude": "9.86", "longitude": "125.55"},
            "incomplete",
        ),
        ({}, {"magnitude": "4.4", "latitude": "9.86", "longitude": "125.55"}, "Below M4.5"),
        (
            {"nearby_alerts_only": True},
            {"magnitude": "5.2", "latitude": "20", "longitude": "125.55"},
            "Outside",
        ),
        (
            {},
            {"magnitude": "nan", "latitude": "9.86", "longitude": "125.55"},
            "valid main magnitude",
        ),
    ],
)
def test_ineligible_event_and_account_reasons(changes, event, reason):
    response = account_view(profile(**changes), event)
    assert all(not channel["eligible"] for channel in response["channels"].values())
    assert all(reason in channel["reason"] for channel in response["channels"].values())
