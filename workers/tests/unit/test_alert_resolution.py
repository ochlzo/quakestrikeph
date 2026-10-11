import logging
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from quakestrike.alert_worker.worker import handle_alert_command
from quakestrike.application.alerts import AlertClaim, ResolveAlertRecipients, SmsSupportUnavailable

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
        self.completed = False
        self.root = AlertClaim(uuid4(), uuid4(), uuid4(), uuid4(), 4.2, 14.123456, 121.123456)

    def claim(self, *_):
        return self.root

    def candidate_page(self, claim, after):
        return self.accounts if after is None else []

    def renew(self, claim):
        assert claim == self.root

    def record(self, claim, recipients):
        self.recorded.extend(recipients)

    def complete(self, claim):
        self.completed = True
        return bool(self.recorded)


class Support:
    def __init__(self, supported=True):
        self.value = supported
        self.calls = []

    def supported(self, phone):
        self.calls.append(phone)
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


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


def test_sms_unavailable_keeps_email_and_does_not_complete_scan():
    store, result = resolve([account()], Support(SmsSupportUnavailable("sanitized")))
    assert result.status == "incomplete"
    assert result.claim == store.root
    assert [r["channel"] for r in store.recorded] == ["email"]
    assert not store.completed
    store, result = resolve([account()], Support(False))
    assert result.status == "resolved"
    assert [r["channel"] for r in store.recorded] == ["email"]


def test_invalid_queue_payload_does_not_access_store():
    assert (
        handle_alert_command(
            {"message_version": 2}, store=None, support=None, logger=logging.getLogger(__name__)
        )
        == "rejected"
    )


def test_empty_roster_result_does_not_expose_a_cleared_claim():
    store = MemoryStore([])
    store.complete = lambda claim: False
    result = ResolveAlertRecipients(store, Support()).execute(uuid4(), uuid4(), uuid4())
    assert result.status == "resolved"
    assert result.claim is None


def test_support_failure_result_keeps_only_bounded_diagnostics():
    _, result = resolve([account()], Support(SmsSupportUnavailable("sms_support_configuration")))
    assert result.support_failures == ("sms_support_configuration",)
    _, result = resolve([account()], Support(SmsSupportUnavailable("secret@example.invalid")))
    assert result.support_failures == ("sms_support_unavailable",)
