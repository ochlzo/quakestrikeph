from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from quakestrike.application.alerts import AlertClaim, ResolveAlertRecipients

NOW = datetime(2026, 10, 11, tzinfo=UTC)


def account(**changes):
    value = dict(
        user_id=uuid4(),
        email="Reader@example.invalid",
        email_enabled=True,
        email_verified_at=NOW,
        mobile_number="+639171234567",
        sms_enabled=True,
        mobile_verified_at=NOW,
        account_status="active",
        onboarding_completed_at=NOW,
        alert_trigger_magnitude=Decimal("4.2"),
        nearby_alerts_only=False,
        alert_location_latitude=None,
        alert_location_longitude=None,
        alert_trigger_distance_km=None,
    )
    return value | changes


class MemoryStore:
    def __init__(self, accounts):
        self.accounts = accounts
        self.recorded = []
        self.root = AlertClaim(uuid4(), uuid4(), uuid4(), uuid4(), 4.2, 14.123456, 121.123456)

    def claim(self, *_):
        return self.root

    def candidate_page(self, claim, after):
        if after is not None:
            return []
        return [
            {
                **account,
                "resolved_channels": {
                    row["channel"] for row in self.recorded if row["user_id"] == account["user_id"]
                },
            }
            for account in self.accounts
        ]

    def renew(self, claim):
        assert claim == self.root

    def record(self, claim, recipients):
        self.recorded.extend(recipients)

    def complete(self, claim):
        return bool(self.recorded)


class Support:
    def supported(self, phone):
        return True


def resolve(accounts, support=None):
    store = MemoryStore(accounts)
    support = support or Support()
    result = ResolveAlertRecipients(store, support).execute(uuid4(), uuid4(), uuid4())
    return store, result


def test_exact_magnitude_and_distance_boundaries_keep_each_channel():
    # One equatorial degree with Earth radius 6371.0088 km.
    distance = 111.1950802335329
    for radius, channels in ((distance, {"email", "sms"}), (distance - 0.000001, set())):
        store = MemoryStore(
            [
                account(
                    nearby_alerts_only=True,
                    alert_location_latitude=0,
                    alert_location_longitude=1,
                    alert_trigger_distance_km=radius,
                )
            ]
        )
        store.root = replace(store.root, latitude=0, longitude=0)
        result = ResolveAlertRecipients(store, Support()).execute(uuid4(), uuid4(), uuid4())
        assert result.status == "resolved"
        assert {r["channel"] for r in store.recorded} == channels


def test_all_exclusions_preserve_independent_opt_in_channels():
    store, _ = resolve(
        [
            account(account_status="suspended"),
            account(account_status="closed"),
            account(onboarding_completed_at=None),
            account(alert_trigger_magnitude=Decimal("4.3")),
            account(nearby_alerts_only=True),
            account(email_enabled=False, sms_enabled=False),
            account(email_verified_at=None, sms_enabled=False),
            account(mobile_verified_at=None, email_enabled=False),
        ]
    )
    assert store.recorded == []
    store, _ = resolve([account(email_enabled=False), account(sms_enabled=False)])
    assert [r["channel"] for r in store.recorded] == ["sms", "email"]
