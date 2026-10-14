import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from quakestrike.alert_testing.application.delivery import Delivery
from quakestrike.alert_testing.application.scenarios import Scenarios
from quakestrike.alert_testing.application.sessions import Sessions
from quakestrike.alert_testing.application.submissions import Submissions
from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.infrastructure.deliveries import RedisDeliveryStore
from quakestrike.alert_testing.infrastructure.preparation import PreparationSigner
from quakestrike.alert_testing.infrastructure.redis import CONTROL_KEY, RedisSessionStore
from quakestrike.alert_testing.interface.consumer import Consumer
from quakestrike.alert_testing.interface.http import PrivateServer
from quakestrike.application.alert_delivery import SubmissionResult
from quakestrike.application.alerts import SmsSupportUnavailable
from quakestrike.infrastructure.geography.province import resolve_province_label

from .test_alert_testing_scenarios import inputs as inputs_fixture
from .test_alert_testing_sessions import PrivateClient
from .test_alert_testing_sessions import redis_client as redis_fixture

pytestmark = pytest.mark.integration
redis_client = redis_fixture
inputs = inputs_fixture


class Accounts:
    def __init__(self):
        now = datetime.now(UTC)
        self.account = {
            "user_id": uuid4(),
            "display_name": "Selected Tester",
            "account_status": "active",
            "onboarding_completed_at": now,
            "alert_trigger_magnitude": Decimal("5.2"),
            "nearby_alerts_only": False,
            "alert_location_latitude": Decimal("9.86"),
            "alert_location_longitude": Decimal("125.55"),
            "alert_trigger_distance_km": Decimal("50"),
            "email": "private@example.invalid",
            "email_verified_at": now,
            "email_enabled": True,
            "mobile_number": "+639171234567",
            "mobile_verified_at": now,
            "sms_enabled": True,
        }

    def search(self, query, selected, page, size):
        assert selected == [str(self.account["user_id"])], "Only the frozen selection is resolved"
        return {"accounts": [self.account], "total": 1, "page": 1, "pages": 1}


class Provider:
    def __init__(self, channel):
        self.channel, self.calls = channel, []
        self.outcome = SubmissionResult("accepted", reference=f"fake-{channel}")
        self.callback = None

    def submit(self, request):
        self.calls.append(request)
        if self.callback:
            self.callback(request)
        return self.outcome


@contextmanager
def workflow(client):
    sessions = Sessions(RedisSessionStore(client))
    signer = PreparationSigner("disposable-test-only-signing-key-32-bytes")
    store = RedisDeliveryStore(client, "https://bulletin.example.invalid")
    accounts = Accounts()
    providers = {channel: Provider(channel) for channel in ("sms", "email")}
    support = SimpleNamespace(supported=lambda phone: True)
    server = PrivateServer(
        sessions,
        Path("."),
        port=0,
        scenarios=Scenarios(sessions, signer=signer),
        submissions=Submissions(sessions, store, signer),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    api = PrivateClient(server)
    owner = api.request("start")[1]["session_id"]
    delivery = Delivery(sessions, store, accounts, support, providers, resolve_province_label)
    harness = SimpleNamespace(
        api=api,
        owner=owner,
        store=store,
        accounts=accounts,
        providers=providers,
        support=support,
        signer=signer,
        sessions=sessions,
        consumer=Consumer(store, delivery, "consumer-one"),
        delivery=delivery,
    )
    try:
        yield harness
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def request(h, operation, **body):
    return h.api.request(
        operation, path=f"/api/test/scenarios/{operation}", body={"session_id": h.owner, **body}
    )


def prepare(h, inputs):
    status, scenario = request(h, "prepare", inputs=inputs)
    assert status == 200
    return scenario


def submit(h, inputs, scenario):
    return request(
        h, "submit", inputs=inputs, scenario=scenario, selected=[str(h.accounts.account["user_id"])]
    )


def test_api_persists_exact_public_envelope_and_one_logical_stream_job(redis_client, inputs):
    ordinary = f"ordinary:alert:queue:{uuid4()}"
    redis_client.rpush(ordinary, "untouched-command")
    try:
        with workflow(redis_client) as h:
            scenario = prepare(h, inputs)
            assert not list(redis_client.scan_iter(match=h.store.key(h.owner, "*")))
            code, result = submit(h, inputs, scenario)
            assert code == 200 and result["queue_status"] == "enqueued"
            event = scenario["event_id"]
            envelope = redis_client.get(h.store.key(h.owner, f"scenario:{event}"))
            record = json.loads(envelope)
            assert record["scenario"] == scenario
            for field in ("event_revision_id", "forecast_id", "model_release_id"):
                assert len(record[field]) == 36
            assert submit(h, inputs, scenario) == (200, result)
            assert redis_client.get(h.store.key(h.owner, f"scenario:{event}")) == envelope
            commands = redis_client.xrange(h.store.key(h.owner, "queue"))
            assert len(commands) == 1
            assert set(commands[0][1]) == {"message_version", "session_id", "event_id", "job_id"}
            assert h.consumer.once(h.owner)
            assert not h.consumer.once(h.owner)
            final = request(h, "results", event_id=event)[1]
            assert final["counts"]["accepted"] == 2 and final["counts"]["delivered"] == 0
            assert "private@example.invalid" not in json.dumps(final)
            assert "+639171234567" not in json.dumps(final)
            assert "saved_latitude" not in json.dumps(final)
            for channel, provider in h.providers.items():
                assert len(provider.calls) == 1
                call = provider.calls[0]
                assert f"/forecasts/{event}?test=true" in call.body
                assert "Original 24-hour forecast window:" not in call.body
                if channel == "email":
                    assert call.attempt_id.startswith(f"test:{h.owner}:{event}:")
                    assert "Possible maximum magnitude: M4.2" in call.body
                else:
                    assert not call.body.startswith("QuakeStrike PH")
            newer = prepare(h, inputs)
            assert submit(h, inputs, newer)[0] == 200 and newer["event_id"] != event
            history = request(h, "history")[1]["scenarios"]
            assert {item["event_id"] for item in history} == {event, newer["event_id"]}
            deadline = scenario["expires_at_ms"]
            assert all(
                redis_client.pexpiretime(key) == deadline
                for key in redis_client.scan_iter(match=h.store.key(h.owner, "*"))
            )
            assert redis_client.lrange(ordinary, 0, -1) == ["untouched-command"]
    finally:
        redis_client.unlink(ordinary)


@pytest.mark.parametrize(
    "tamper", ["missing", "token", "observation", "input", "deadline", "owner"]
)
def test_invalid_browser_preparation_creates_no_record(redis_client, inputs, tamper):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        if tamper == "missing":
            scenario = None
        elif tamper == "token":
            scenario["preparation_token"] = "é" * 64
        elif tamper == "observation":
            scenario["observations"][0]["latitude"] += 1
        elif tamper == "input":
            inputs["radius"] = "43"
        elif tamper == "deadline":
            scenario["expires_at_ms"] += 1
        elif tamper == "owner":
            scenario["session_id"] = str(uuid4())
        assert submit(h, inputs, scenario)[0] == 400
        assert not list(redis_client.scan_iter(match=h.store.key(h.owner, "*")))


def test_expired_forecast_and_stale_session_reject_submission(redis_client, inputs):
    with workflow(redis_client) as h:
        inputs["time"] = (datetime.now(UTC) - timedelta(hours=17)).strftime("%Y-%m-%dT%H:%M")
        expired = prepare(h, inputs)
        assert submit(h, inputs, expired)[0] == 400
        assert h.api.request("end", h.owner)[0] == 200
        assert submit(h, inputs, expired)[0] == 409


@pytest.mark.parametrize("channel", ["email", "sms"])
def test_settings_rechecked_independently_before_each_send(redis_client, inputs, channel):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        assert submit(h, inputs, scenario)[0] == 200
        h.accounts.account[f"{channel}_enabled"] = False
        assert h.consumer.once(h.owner)
        result = request(h, "results", event_id=scenario["event_id"])[1]
        assert result["counts"]["skipped"] == 1 and result["counts"]["accepted"] == 1
        assert len(h.providers[channel].calls) == 0


@pytest.mark.parametrize("support", [False, None])
def test_sms_support_does_not_block_email(redis_client, inputs, support):
    with workflow(redis_client) as h:

        def supported(phone):
            if support is None:
                raise SmsSupportUnavailable("unknown")
            return support

        h.support.supported = supported
        scenario = prepare(h, inputs)
        submit(h, inputs, scenario)
        h.consumer.once(h.owner)
        assert not h.providers["sms"].calls and len(h.providers["email"].calls) == 1


def test_lost_submission_and_publication_responses_reuse_original_record(
    redis_client, inputs, monkeypatch
):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        for operation in ("submit", "publish"):
            original = h.store.scripts[operation]

            def lost(*args, original=original, **kwargs):
                original(*args, **kwargs)
                raise RedisError("lost response with private destination must not appear")

            monkeypatch.setitem(h.store.scripts, operation, lost)
            assert submit(h, inputs, scenario) == (
                503,
                {"error": "dependency-unavailable", "dependency": "Redis"},
            )
            monkeypatch.setitem(h.store.scripts, operation, original)
        assert submit(h, inputs, scenario)[0] == 200
        assert redis_client.xlen(h.store.key(h.owner, "queue")) == 1
        assert h.consumer.once(h.owner)
        assert all(len(provider.calls) == 1 for provider in h.providers.values())


def test_queue_failure_remains_pending_and_recovers(redis_client, inputs):
    with workflow(redis_client) as h:
        redis_client.set(h.store.key(h.owner, "queue"), "broken-dependency")
        scenario = prepare(h, inputs)
        code, result = submit(h, inputs, scenario)
        assert code == 200 and result["queue_status"] == "pending"
        assert not any(provider.calls for provider in h.providers.values())
        redis_client.unlink(h.store.key(h.owner, "queue"))
        h.store.recover_publications(h.owner)
        assert submit(h, inputs, scenario)[1]["queue_status"] == "enqueued"


def test_concurrent_duplicates_fence_provider_calls_and_record_before_transport(
    redis_client, inputs
):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: submit(h, inputs, scenario), range(4)))
        assert all(code == 200 for code, _ in results)
        assert redis_client.xlen(h.store.key(h.owner, "queue")) == 1
        fields = redis_client.xrange(h.store.key(h.owner, "queue"))[0][1]
        redis_client.xadd(h.store.key(h.owner, "queue"), fields)
        entered, resume = Event(), Event()

        def paused(request):
            rows = redis_client.hvals(h.store.key(h.owner, f"recipients:{scenario['event_id']}"))
            assert any(json.loads(raw).get("attempt_id") in request.attempt_id for raw in rows)
            entered.set()
            assert resume.wait(5)

        h.providers["email"].callback = paused
        other = Consumer(h.store, h.delivery, "consumer-two")
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(h.consumer.once, h.owner)
            try:
                assert entered.wait(5)
                assert other.once(h.owner)
            finally:
                resume.set()
            assert running.result()
        assert all(len(provider.calls) == 1 for provider in h.providers.values())


def test_unknown_and_interrupted_attempts_are_not_resent_on_stream_recovery(redis_client, inputs):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        submit(h, inputs, scenario)
        message, fields = h.store.next_command(h.owner, "crashed-reader")
        user = str(h.accounts.account["user_id"])
        h.store.begin(
            h.owner,
            scenario["event_id"],
            user,
            "email",
            {
                "status": "unknown",
                "reason": "Interrupted authorized call.",
                "token": str(uuid4()),
            },
            call=True,
        )
        redis_client.xclaim(
            h.store.key(h.owner, "queue"),
            "test-delivery-v1",
            "crashed-reader",
            0,
            [message],
            idle=31000,
        )
        h.providers["sms"].outcome = SubmissionResult(
            "unknown", error_code="provider_transport_uncertain"
        )
        assert h.consumer.once(h.owner)
        redis_client.xadd(h.store.key(h.owner, "queue"), fields)
        assert h.consumer.once(h.owner)
        assert not h.providers["email"].calls and len(h.providers["sms"].calls) == 1
        result = request(h, "results", event_id=scenario["event_id"])[1]
        assert result["counts"]["unknown"] == 2


def test_closure_waits_for_bounded_calls_and_late_results_cannot_recreate_state(
    redis_client, inputs
):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        submit(h, inputs, scenario)
        entered, resume = Event(), Event()

        def paused(request):
            entered.set()
            assert resume.wait(5)

        h.providers["email"].callback = paused
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(h.consumer.once, h.owner)
            try:
                assert entered.wait(5)
                ended = h.api.request("end", h.owner)[1]
                assert ended["status"] == "ending"
                assert h.api.request("start")[0] == 409
                assert request(h, "results", event_id=scenario["event_id"])[0] == 409
                # Advance coordination after its bounded transport deadline, without sleeping.
                redis_client.hset(CONTROL_KEY, "calls_until_ms", 0)
                assert h.api.request("cleanup", h.owner)[1]["status"] == "ended"
                replacement = h.api.request("start")[1]["session_id"]
                assert replacement != h.owner
            finally:
                resume.set()
            with pytest.raises(SessionConflict):
                running.result()
        assert not list(redis_client.scan_iter(match=h.store.key(h.owner, "*")))
        assert not h.providers["sms"].calls
        assert redis_client.hget(CONTROL_KEY, "session_id") == replacement


def test_account_dependency_failure_keeps_queue_recoverable(redis_client, inputs, monkeypatch):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        submit(h, inputs, scenario)
        original = h.accounts.search

        def unavailable(*args):
            raise RedisError("simulated dependency")

        monkeypatch.setattr(h.accounts, "search", unavailable)
        with pytest.raises(RedisError):
            h.consumer.once(h.owner)
        assert not any(provider.calls for provider in h.providers.values())
        monkeypatch.setattr(h.accounts, "search", original)
        message = redis_client.xrange(h.store.key(h.owner, "queue"))[0][0]
        redis_client.xclaim(
            h.store.key(h.owner, "queue"),
            "test-delivery-v1",
            "consumer-one",
            0,
            [message],
            idle=31000,
        )
        assert h.consumer.once(h.owner)


@pytest.mark.parametrize(
    "change",
    ["account_status", "onboarding_completed_at", "email_verified_at", "threshold", "nearby"],
)
def test_ordinary_eligibility_rechecked_after_queueing(redis_client, inputs, change):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        submit(h, inputs, scenario)
        if change == "account_status":
            h.accounts.account[change] = "suspended"
        elif change in ("onboarding_completed_at", "email_verified_at"):
            h.accounts.account[change] = None
        elif change == "threshold":
            h.accounts.account["alert_trigger_magnitude"] = Decimal("5.3")
        else:
            h.accounts.account.update(
                nearby_alerts_only=True, alert_location_latitude=Decimal("50")
            )
        h.consumer.once(h.owner)
        assert not h.providers["email"].calls
        assert len(h.providers["sms"].calls) == (1 if change == "email_verified_at" else 0)


def test_nearby_variants_and_changed_sms_destination(redis_client, inputs):
    with workflow(redis_client) as h:
        h.accounts.account["nearby_alerts_only"] = True
        scenario = prepare(h, inputs)
        submit(h, inputs, scenario)

        def change_destination(phone):
            h.accounts.account["mobile_number"] = "+639171111111"
            return True

        h.support.supported = change_destination
        h.consumer.once(h.owner)
        assert not h.providers["sms"].calls
        assert "near your saved alert location" in h.providers["email"].calls[0].body
        assert "near your saved alert location" in h.providers["email"].calls[0].subject


def test_identity_cannot_be_reused_for_a_changed_roster(redis_client, inputs):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        assert submit(h, inputs, scenario)[0] == 200
        assert (
            request(h, "submit", inputs=inputs, scenario=scenario, selected=[str(uuid4())])[0]
            == 400
        )
        assert redis_client.xlen(h.store.key(h.owner, "queue")) == 1


def test_expiry_between_attempt_and_authorization_blocks_transport(
    redis_client, inputs, monkeypatch
):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        submit(h, inputs, scenario)
        allow = h.store.allow

        def expire_before_authorization(owner, event, row):
            redis_client.hset(CONTROL_KEY, "expires_at_ms", 0)
            return allow(owner, event, row)

        monkeypatch.setattr(h.store, "allow", expire_before_authorization)
        with pytest.raises(SessionConflict):
            h.consumer.once(h.owner)
        assert not any(provider.calls for provider in h.providers.values())


@pytest.mark.parametrize("status", ["permanent", "transient", "unknown"])
def test_provider_rejections_and_uncertainty_remain_distinct(redis_client, inputs, status):
    with workflow(redis_client) as h:
        h.providers["email"].outcome = SubmissionResult(status, error_code="provider_failure")
        scenario = prepare(h, inputs)
        submit(h, inputs, scenario)
        h.consumer.once(h.owner)
        final = request(h, "results", event_id=scenario["event_id"])[1]
        expected = "unknown" if status == "unknown" else "failed"
        assert final["counts"][expected] == 1 and final["counts"]["accepted"] == 1


def test_forecast_expiry_at_final_authorization_blocks_transport(redis_client, inputs, monkeypatch):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        submit(h, inputs, scenario)
        allow = h.store.allow
        original_deadline = redis_client.hget(CONTROL_KEY, "expires_at_ms")

        def expire_forecast(owner, event, row):
            key = h.store.key(owner, f"scenario:{event}")
            record = json.loads(redis_client.get(key))
            # Advance only the forecast fixture to expiry, without waiting 24 hours.
            record["scenario"]["forecast"]["window_end_ms"] = 0
            redis_client.set(key, json.dumps(record), keepttl=True)
            return allow(owner, event, row)

        monkeypatch.setattr(h.store, "allow", expire_forecast)
        assert h.consumer.once(h.owner)
        assert not any(provider.calls for provider in h.providers.values())
        assert redis_client.hget(CONTROL_KEY, "expires_at_ms") == original_deadline
        assert h.sessions.read()["status"] == "active"


def test_partial_storage_repair_preserves_original_public_identity(redis_client, inputs):
    with workflow(redis_client) as h:
        queue = h.store.key(h.owner, "queue")
        redis_client.set(queue, "publication-unavailable")
        scenario = prepare(h, inputs)
        assert submit(h, inputs, scenario)[1]["queue_status"] == "pending"
        public_key = h.store.key(h.owner, f"scenario:{scenario['event_id']}")
        original = redis_client.get(public_key)
        # Emulate an interrupted script retaining its first, self-contained job write.
        redis_client.unlink(
            public_key, h.store.key(h.owner, "history"), h.store.key(h.owner, "outbox"), queue
        )
        assert submit(h, inputs, scenario)[1]["queue_status"] == "enqueued"
        assert redis_client.get(public_key) == original
        assert redis_client.xlen(queue) == 1


def test_history_pages_keep_earlier_forecast_links(redis_client, inputs):
    with workflow(redis_client) as h:
        inputs.update(local="1", background="0", spillover="0")
        events = []
        for _ in range(51):
            scenario = prepare(h, inputs)
            events.append(scenario["event_id"])
            assert submit(h, inputs, scenario)[0] == 200
        first = request(h, "history", page=1)[1]
        second = request(h, "history", page=2)[1]
        assert first["pages"] == 2 and len(first["scenarios"]) == 50
        assert second["page"] == 2 and len(second["scenarios"]) == 1
        assert {row["event_id"] for row in first["scenarios"] + second["scenarios"]} == set(events)
        assert request(h, "history", page=10000)[1]["page"] == 2
        assert request(h, "history", page=0)[0] == 400


def test_consumer_configuration_cannot_replace_frozen_forecast_url(redis_client, inputs):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        saved = submit(h, inputs, scenario)[1]
        h.store.public_base_url = "https://different.example.invalid"
        assert h.consumer.once(h.owner)
        assert all(
            saved["forecast_url"] in provider.calls[0].body for provider in h.providers.values()
        )
