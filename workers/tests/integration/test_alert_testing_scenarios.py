import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

import pytest

from quakestrike.alert_testing.application import scenarios as scenario_module
from quakestrike.alert_testing.application.scenarios import Scenarios
from quakestrike.alert_testing.application.sessions import Sessions
from quakestrike.alert_testing.infrastructure.redis import CONTROL_KEY, PREFIX, RedisSessionStore
from quakestrike.alert_testing.interface.http import PrivateServer

from .test_alert_testing_sessions import PrivateClient
from .test_alert_testing_sessions import redis_client as redis_fixture

pytestmark = pytest.mark.integration
redis_client = redis_fixture
PREPARE_PATH = "/api/test/scenarios/prepare"


@contextmanager
def scenario_api(redis_client):
    sessions = Sessions(RedisSessionStore(redis_client))
    server = PrivateServer(sessions, Path("."), port=0, scenarios=Scenarios(sessions))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield PrivateClient(server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.fixture
def inputs():
    payload = json.loads(
        (Path(__file__).parents[1] / "fixtures/alert_testing/scenario.json").read_text()
    )
    # Freeze an anchor one hour ago in Philippine time without depending on the host zone.
    payload["time"] = (datetime.now(UTC) + timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M")
    return payload


def prepare(api, owner, inputs, headers=None):
    return api.request(
        "prepare", path=PREPARE_PATH, body={"session_id": owner, "inputs": inputs}, headers=headers
    )


def test_api_returns_exact_preparation_without_records_or_work(redis_client, inputs):
    with scenario_api(redis_client) as api:
        session = api.request("start")[1]
        owner = session["session_id"]
        before = redis_client.hgetall(CONTROL_KEY)
        code, first = prepare(api, owner, inputs)
        assert code == 200 and first["version"] == 1 and first["session_id"] == owner
        assert first["expires_at_ms"] == session["expires_at_ms"]
        assert (
            first["forecast"]["window_end_ms"] - first["forecast"]["window_start_ms"] == 86_400_000
        )
        points = first["observations"]
        assert len(points) == 22 and len({point["event_id"] for point in points}) == 22
        assert all(point["location_description"] for point in points)
        assert all(
            first["event"]["event_time_ms"] < point["event_time_ms"] <= first["prepared_at_ms"]
            for point in points
        )
        assert sum(point["kind"] == "inside" for point in points) == 16
        assert sum(point["kind"] == "spillover" for point in points) == 2
        assert sum(point["kind"] == "background" for point in points) == 4
        code, second = prepare(api, owner, inputs)
        assert code == 200 and second["event_id"] != first["event_id"]
        assert [(point["latitude"], point["longitude"]) for point in points] != [
            (point["latitude"], point["longitude"]) for point in second["observations"]
        ]
        assert redis_client.hgetall(CONTROL_KEY) == before
        assert list(redis_client.scan_iter(match=PREFIX + "*")) == [CONTROL_KEY]
        assert api.request(path=PREPARE_PATH)[0] == 404
        assert api.request("send", path="/api/test/scenarios", body={})[0] == 404


@pytest.mark.parametrize(
    "field,value",
    [
        ("radius", "0"),
        ("radius", "NaN"),
        ("p4", "90"),
        ("q50", ""),
        ("longitude", "181"),
        ("local", "1.1"),
        ("spillover", "18"),
        ("time", "invalid"),
    ],
)
def test_api_exposes_bounded_field_validation(redis_client, inputs, field, value):
    with scenario_api(redis_client) as api:
        owner = api.request("start")[1]["session_id"]
        inputs[field] = value
        code, result = prepare(api, owner, inputs)
        assert code == 400 and result["error"] == "invalid-scenario"
        assert field in result["fields"]
        assert list(redis_client.scan_iter(match=PREFIX + "*")) == [CONTROL_KEY]


def test_preparation_requires_exact_private_request_protections(redis_client, inputs):
    with scenario_api(redis_client) as api:
        owner = api.request("start")[1]["session_id"]
        for headers in (
            {"Host": "quakestrikeph.com"},
            {"Host": "quakestrikeph.qzz.io"},
            {"Origin": "https://public.invalid"},
            {"X-QuakeStrike-Test": ""},
            {"Sec-Fetch-Site": "cross-site"},
        ):
            assert prepare(api, owner, inputs, headers)[0] == 403
        assert prepare(api, owner, inputs, {"Content-Type": "text/plain"})[0] == 400
        oversized = {**inputs, "location": "x" * 8192}
        assert prepare(api, owner, oversized)[0] == 400
        assert prepare(api, owner, {**inputs, "extra": "unknown"})[0] == 400
        assert prepare(api, "invalid", inputs)[0] == 400


def test_preparation_rejects_inactive_wrong_owner_and_expired_sessions(redis_client, inputs):
    with scenario_api(redis_client) as api:
        assert prepare(api, str(uuid4()), inputs)[0] == 409
        session = api.request("start")[1]
        owner = session["session_id"]
        assert prepare(api, str(uuid4()), inputs)[0] == 409
        redis_client.hset(CONTROL_KEY, "expires_at_ms", session["server_time_ms"] - 1)
        assert prepare(api, owner, inputs)[0] == 409


@pytest.mark.parametrize("closing", ["end", "expiry", "replacement"])
def test_closure_during_preparation_rejects_response(redis_client, inputs, monkeypatch, closing):
    entered, resume = Event(), Event()
    generate = scenario_module.generate_observations

    def paused(*args):
        entered.set()
        assert resume.wait(3)
        return generate(*args)

    monkeypatch.setattr(scenario_module, "generate_observations", paused)
    with scenario_api(redis_client) as api:
        session = api.request("start")[1]
        owner = session["session_id"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(prepare, api, owner, inputs)
            try:
                assert entered.wait(3)
                if closing == "expiry":
                    redis_client.hset(CONTROL_KEY, "expires_at_ms", session["server_time_ms"] - 1)
                else:
                    assert api.request("end", owner)[0] == 200
                    if closing == "replacement":
                        assert api.request("start")[1]["session_id"] != owner
            finally:
                resume.set()
            assert future.result() == (409, {"error": "session-conflict"})
        assert list(redis_client.scan_iter(match=PREFIX + "*")) == [CONTROL_KEY]
