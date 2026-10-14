"""Private producer -> actual Stream -> fake transports -> actual Backend HTTP."""

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
from sqlalchemy import select

from integration.conftest import clean_database as clean_database_fixture
from integration.conftest import migrated_engine as migrated_engine_fixture
from integration.test_alert_resolution import account
from integration.test_alert_testing_accounts import (
    restricted_accounts as restricted_accounts_fixture,
)
from integration.test_alert_testing_delivery import Provider
from integration.test_alert_testing_scenarios import inputs as inputs_fixture
from integration.test_alert_testing_sessions import PrivateClient
from integration.test_alert_testing_sessions import redis_client as redis_fixture
from quakestrike.alert_testing.application.delivery import Delivery
from quakestrike.alert_testing.application.reconciliation import Reconciliation
from quakestrike.alert_testing.application.scenarios import Scenarios
from quakestrike.alert_testing.application.sessions import Sessions
from quakestrike.alert_testing.application.submissions import Submissions
from quakestrike.alert_testing.application.testers import Testers as AccountWorkflow
from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.infrastructure.deliveries import RedisDeliveryStore
from quakestrike.alert_testing.infrastructure.preparation import PreparationSigner
from quakestrike.alert_testing.infrastructure.redis import CONTROL_KEY, RedisSessionStore
from quakestrike.alert_testing.interface.consumer import Consumer
from quakestrike.alert_testing.interface.http import PrivateServer
from quakestrike.application.sms_polling import SmsOutcome
from quakestrike.infrastructure.database.tables import alert_jobs, users
from quakestrike.infrastructure.geography.province import resolve_province_label

pytestmark = pytest.mark.integration
clean_database = clean_database_fixture
migrated_engine = migrated_engine_fixture
restricted_accounts = restricted_accounts_fixture
inputs = inputs_fixture
redis_client = redis_fixture


def public_request(path, body=None, token="TEST_ONLY_CALLBACK_TOKEN_FOR_WORKFLOW"):
    base = os.environ["TEST_ALERT_BACKEND_URL"]
    assert base == "http://alert-testing-backend-fixture:3000"
    request = Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        payload = response.read()
        return response.status, json.loads(payload) if payload.startswith(b"{") else None


@pytest.mark.parametrize("closure", ["end", "expiry"])
def test_complete_disposable_workflow(
    redis_client, restricted_accounts, migrated_engine, inputs, closure
):
    if not os.environ.get("TEST_ALERT_BACKEND_URL"):
        pytest.skip("Run the separately documented disposable Backend workflow fixture.")
    selected = account(migrated_engine)
    account(migrated_engine, mobile_number="+639171234568")
    reader = restricted_accounts[0]
    sessions = Sessions(RedisSessionStore(redis_client))
    signer = PreparationSigner("disposable-workflow-preparation-key-32-bytes")
    store = RedisDeliveryStore(redis_client, "https://bulletin.example.invalid")
    server = PrivateServer(
        sessions,
        Path("."),
        port=0,
        origin="https://quakestrike-vps.tailf8b2fd.ts.net:8443",
        testers=AccountWorkflow(reader, sessions),
        scenarios=Scenarios(sessions, signer=signer),
        submissions=Submissions(sessions, store, signer),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    api = PrivateClient(server)
    host = {"Host": server.authority}
    ordinary = f"ordinary:queue:{uuid4()}"
    redis_client.rpush(ordinary, "preserve")
    providers = {channel: Provider(channel) for channel in ("sms", "email")}
    before = None
    try:
        with migrated_engine.connect() as connection:
            before = connection.execute(select(users)).all()
        assert api.request("start")[0] == 403
        assert (
            api.request(
                "start", headers={**host, "Origin": "https://quakestrike-vps.tailf8b2fd.ts.net"}
            )[0]
            == 403
        )
        code, session = api.request("start", headers=host)
        assert code == 200
        owner = session["session_id"]

        def private(action, body):
            return api.request(
                action,
                headers=host,
                path=f"/api/test/scenarios/{action}",
                body={"session_id": owner, **body},
            )

        code, scenario = private("prepare", {"inputs": inputs})
        assert code == 200 and not list(redis_client.scan_iter(match=store.key(owner, "*")))
        body = {"inputs": inputs, "scenario": scenario, "selected": [str(selected)]}
        code, submitted = private("submit", body)
        assert code == 200 and submitted["queue_status"] == "enqueued"
        assert private("submit", body) == (code, submitted)
        event = scenario["event_id"]
        detail_path = f"/api/v1/earthquakes/{event}?test=true"
        code, first = public_request(detail_path)
        assert code == 200 and public_request(detail_path)[1]["item"] == first["item"]
        assert first["item"]["eventId"] == event
        assert public_request(f"/api/v1/earthquakes/{event}")[0] == 404
        window = {
            "dateFrom": datetime.fromtimestamp(
                scenario["forecast"]["window_start_ms"] / 1000, UTC
            ).isoformat(),
            "dateTo": datetime.fromtimestamp(
                scenario["forecast"]["window_end_ms"] / 1000, UTC
            ).isoformat(),
            "limit": 100,
        }
        observations_path = f"/api/v1/earthquakes/{event}/observations?test=true"
        code, observations = public_request(observations_path, window)
        assert code == 200
        assert public_request(observations_path, window)[1]["items"] == observations["items"]
        assert {item["eventId"] for item in observations["items"]} == {
            item["event_id"] for item in scenario["observations"]
        }
        saved = {item["event_id"]: item for item in scenario["observations"]}
        for item in observations["items"]:
            expected = saved[item["eventId"]]
            for field in ("magnitude", "latitude", "longitude"):
                assert item[field] == expected[field]
            assert item["depthKm"] == expected["depth_km"]
            assert (
                int(
                    datetime.fromisoformat(item["eventTime"].replace("Z", "+00:00")).timestamp()
                    * 1000
                )
                == expected["event_time_ms"]
            )
        assert str(selected) not in json.dumps(first) + json.dumps(observations)

        def callback(call, token="TEST_ONLY_CALLBACK_TOKEN_FOR_WORKFLOW"):
            return public_request(
                "/api/v1/callbacks/brevo",
                {
                    "event": "delivered",
                    "message-id": "<fake-email>",
                    "ts_event": int(time.time()),
                    "X-Mailin-custom": f"quakestrike-attempt:{call.attempt_id}",
                },
                token,
            )[0]

        def early_email(call):
            assert callback(call, "WRONG") == 401
            assert callback(call) == 204

        providers["email"].callback = early_email
        delivery = Delivery(
            sessions,
            store,
            reader,
            SimpleNamespace(supported=lambda _: True),
            providers,
            resolve_province_label,
        )
        consumer = Consumer(store, delivery, "release-readiness")
        assert consumer.once(owner)
        assert not consumer.once(owner)
        for provider in providers.values():
            assert len(provider.calls) == 1
            assert f"/forecasts/{event}?test=true" in provider.calls[0].body
        results = private("results", {"event_id": event})[1]
        assert results["counts"]["delivered"] == 1 and results["counts"]["accepted"] == 1
        poller = Reconciliation(store, SimpleNamespace(poll=lambda _: SmsOutcome("delivered")))
        assert poller.once(owner)
        assert private("results", {"event_id": event})[1]["counts"]["delivered"] == 2
        if closure == "end":
            assert api.request("end", owner, headers=host)[0] == 200
        else:
            redis_client.hset(CONTROL_KEY, "expires_at_ms", int(time.time() * 1000) - 1)
        assert public_request(detail_path)[0] == 404
        assert public_request(observations_path, window)[0] == 404
        assert callback(providers["email"].calls[0]) == 204
        assert private("submit", body)[0] == 409
        with pytest.raises(SessionConflict):
            consumer.once(owner)
        # An authorized test call holds cleanup closed for at most 15 seconds.
        deadline = time.monotonic() + 18
        while time.monotonic() < deadline:
            sessions.maintain()
            if not list(redis_client.scan_iter(match=store.key(owner, "*"))):
                break
            time.sleep(0.1)
        assert not list(redis_client.scan_iter(match=store.key(owner, "*")))
        assert callback(providers["email"].calls[0]) == 204
        assert not list(redis_client.scan_iter(match=store.key(owner, "*")))
        assert redis_client.lrange(ordinary, 0, -1) == ["preserve"]
        with migrated_engine.connect() as connection:
            assert connection.execute(select(users)).all() == before
            assert not connection.execute(select(alert_jobs)).all()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        redis_client.unlink(ordinary)
