import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path
from threading import Barrier, Event, Lock, Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
from redis import Redis
from redis.exceptions import ConnectionError, RedisError

from quakestrike.alert_testing.application.sessions import Sessions
from quakestrike.alert_testing.domain.sessions import CONTROL_RETENTION_MS, SESSION_LIFETIME_MS
from quakestrike.alert_testing.infrastructure.redis import CONTROL_KEY, PREFIX, RedisSessionStore
from quakestrike.alert_testing.interface.http import API_PATH, PrivateServer

pytestmark = pytest.mark.integration


class PrivateClient:
    def __init__(self, server):
        self.server = server
        self.url = f"http://127.0.0.1:{server.server_port}"

    def request(self, action=None, session_id=None, *, headers=None, body=None, path=None):
        payload = (
            body if body is not None else ({} if action == "start" else {"session_id": session_id})
        )
        request_headers = {}
        if action:
            request_headers = {
                "Content-Type": "application/json",
                "Origin": self.server.origin,
                "X-QuakeStrike-Test": "1",
            }
        request_headers.update(headers or {})
        request = Request(
            self.url + (path or API_PATH + (f"/{action}" if action else "")),
            data=json.dumps(payload).encode() if action else None,
            headers=request_headers,
            method="POST" if action else "GET",
        )
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)


@contextmanager
def private_http(store, directory=Path(".")):
    server = PrivateServer(Sessions(store), directory, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield PrivateClient(server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.fixture
def redis_client():
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL is required for disposable Redis workflow tests.")
    client = Redis.from_url(url, decode_responses=True, socket_timeout=2)
    assert not list(client.scan_iter(match=PREFIX + "*")), "Disposable tool namespace must be empty"
    yield client
    for key in client.scan_iter(match=PREFIX + "*"):
        client.unlink(key)
    client.close()


@pytest.fixture
def private_api(redis_client):
    with private_http(RedisSessionStore(redis_client)) as api:
        yield api


def test_concurrent_starts_share_fixed_four_hour_session_without_queueing(
    private_api, redis_client, monkeypatch
):
    simultaneous = Barrier(12)
    connected = Event()
    counter_lock = Lock()
    connection_count = 0
    original_connect = HTTPConnection.connect
    original_accept = private_api.server.get_request

    def connect(client):
        nonlocal connection_count
        original_connect(client)
        with counter_lock:
            connection_count += 1
            if connection_count == 12:
                connected.set()

    def accept_burst():
        connection, address = original_accept()
        # Hold acceptance during the burst, as when the server is briefly busy.
        if not connected.wait(timeout=3):
            connection.close()
            raise TimeoutError("Concurrent clients could not connect before acceptance resumed")
        return connection, address

    monkeypatch.setattr(HTTPConnection, "connect", connect)
    monkeypatch.setattr(private_api.server, "get_request", accept_burst)

    def start(_):
        simultaneous.wait(timeout=5)
        return private_api.request("start")

    with ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(pool.map(start, range(12)))
    assert all(code == 200 for code, _ in responses)
    sessions = [body for _, body in responses]
    first = sessions[0]
    assert {session["session_id"] for session in sessions} == {first["session_id"]}
    assert {session["expires_at_ms"] for session in sessions} == {first["expires_at_ms"]}
    assert first["expires_at_ms"] - first["started_at_ms"] == SESSION_LIFETIME_MS
    assert private_api.request("start")[1]["expires_at_ms"] == first["expires_at_ms"]
    assert private_api.request()[1]["status"] == "active"
    assert list(redis_client.scan_iter(match=PREFIX + "*")) == [CONTROL_KEY]
    assert redis_client.pexpiretime(CONTROL_KEY) == first["expires_at_ms"] + CONTROL_RETENTION_MS


def test_end_is_idempotent_and_preserves_unrelated_keys_and_commands(private_api, redis_client):
    unrelated = f"ordinary-alert-queue:{uuid4()}"
    adjacent = PREFIX + f"other-tool:{uuid4()}"
    redis_client.rpush(unrelated, "production-command")
    redis_client.set(adjacent, "unrelated-data")
    try:
        _, session = private_api.request("start")
        owned = PREFIX + session["session_id"] + ":empty-session-fixture"
        redis_client.set(owned, "temporary-data", pxat=session["expires_at_ms"])
        code, ended = private_api.request("end", session["session_id"])
        assert code == 200 and ended["status"] == "ended" and ended["cleanup"] == "complete"
        assert not redis_client.exists(owned)
        assert redis_client.lrange(unrelated, 0, -1) == ["production-command"]
        assert redis_client.get(adjacent) == "unrelated-data"
        assert private_api.request("end", session["session_id"])[1]["status"] == "ended"
        assert private_api.request("cleanup", session["session_id"])[1]["status"] == "ended"
        _, replacement = private_api.request("start")
        assert replacement["session_id"] != session["session_id"]
        assert private_api.request("end", session["session_id"])[0] == 409
        assert private_api.request("cleanup", session["session_id"])[0] == 409
        assert private_api.request()[1]["session_id"] == replacement["session_id"]
    finally:
        redis_client.unlink(unrelated, adjacent)


def test_expiry_denies_access_before_cleanup_and_never_extends_deadline(private_api, redis_client):
    _, session = private_api.request("start")
    expired_deadline = session["server_time_ms"] - 1
    redis_client.hset(CONTROL_KEY, "expires_at_ms", expired_deadline)
    owned = PREFIX + session["session_id"] + ":pending-cleanup"
    redis_client.set(owned, "temporary-data")
    code, expired = private_api.request()
    assert code == 200 and expired["status"] == "expired"
    assert expired["cleanup"] == "pending" and redis_client.exists(owned)
    assert private_api.request("start")[0] == 409
    assert private_api.request()[1]["expires_at_ms"] == expired_deadline
    code, cleaned = private_api.request("cleanup", session["session_id"])
    assert code == 200 and cleaned["status"] == "expired" and cleaned["cleanup"] == "complete"
    assert not redis_client.exists(owned)
    _, replacement = private_api.request("start")
    assert replacement["status"] == "active" and replacement["session_id"] != session["session_id"]


def test_cleanup_failure_keeps_session_closed_and_can_retry(private_api, redis_client, monkeypatch):
    _, session = private_api.request("start")
    owned = PREFIX + session["session_id"] + ":cleanup-fixture"
    redis_client.set(owned, "temporary-data", pxat=session["expires_at_ms"])
    original = redis_client.unlink

    def fail_unlink(*keys):
        raise RedisError("simulated deletion failure; must not leak into the HTTP response")

    monkeypatch.setattr(redis_client, "unlink", fail_unlink)
    code, failed = private_api.request("end", session["session_id"])
    assert code == 200 and failed["status"] == "cleanup-failure"
    assert redis_client.hget(CONTROL_KEY, "lifecycle") == "closed"
    assert redis_client.exists(owned) and private_api.request("start")[0] == 409
    assert private_api.request()[1]["status"] == "cleanup-failure"
    monkeypatch.setattr(redis_client, "unlink", original)
    assert private_api.request("cleanup", session["session_id"])[1]["status"] == "ended"
    assert not redis_client.exists(owned)


def test_end_closes_before_deletion_and_concurrent_retry_stays_closed(
    private_api, redis_client, monkeypatch
):
    _, session = private_api.request("start")
    owned = PREFIX + session["session_id"] + ":cleanup-fixture"
    redis_client.set(owned, "temporary-data", pxat=session["expires_at_ms"])
    deleting = Event()
    resume = Event()
    original = redis_client.unlink

    def pause_unlink(*keys):
        deleting.set()
        assert resume.wait(3)
        return original(*keys)

    monkeypatch.setattr(redis_client, "unlink", pause_unlink)
    with ThreadPoolExecutor(max_workers=1) as pool:
        ending = pool.submit(private_api.request, "end", session["session_id"])
        try:
            assert deleting.wait(3)
            assert private_api.request()[1]["status"] == "ending"
            assert redis_client.hget(CONTROL_KEY, "lifecycle") == "closed"
            assert private_api.request("start")[0] == 409
            assert private_api.request("cleanup", session["session_id"])[1]["status"] == "ending"
        finally:
            resume.set()
        assert ending.result()[1]["status"] == "ended"


def test_lost_cleanup_lease_recovers_through_private_api(private_api, redis_client):
    _, session = private_api.request("start")
    owned = PREFIX + session["session_id"] + ":cleanup-fixture"
    redis_client.set(owned, "temporary-data", pxat=session["expires_at_ms"])
    redis_client.hset(
        CONTROL_KEY,
        mapping={
            "lifecycle": "closed",
            "cleanup": "running",
            "cleanup_token": str(uuid4()),
            "lease_until_ms": session["server_time_ms"] - 1,
        },
    )
    assert private_api.request("cleanup", session["session_id"])[1]["status"] == "ended"
    assert not redis_client.exists(owned)


def test_dependency_outage_does_not_claim_inactivity_or_success(redis_client, monkeypatch):
    store = RedisSessionStore(redis_client)
    with private_http(store) as api:
        _, session = api.request("start")
        original = store.script

        def unavailable(*args, **kwargs):
            raise ConnectionError("private connection details must not be returned")

        monkeypatch.setattr(store, "script", unavailable)
        for action in (None, "start", "end", "cleanup"):
            code, body = api.request(action, session["session_id"])
            assert code == 503
            assert body == {"error": "dependency-unavailable", "dependency": "Redis"}
        monkeypatch.setattr(store, "script", original)
        assert api.request()[1]["status"] == "active"


def test_private_http_rejects_public_host_cross_origin_and_invalid_actions(
    private_api, redis_client
):
    for hostname in ("quakestrikeph.com", "quakestrikeph.qzz.io"):
        assert private_api.request("start", headers={"Host": hostname})[0] == 403
        assert private_api.request(headers={"Host": hostname})[0] == 403
        assert private_api.request("start", headers={"Origin": f"https://{hostname}"})[0] == 403
    assert private_api.request("start", headers={"X-QuakeStrike-Test": ""})[0] == 403
    assert private_api.request("start", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert private_api.request("start", body={"scenario": "not-allowed"})[0] == 400
    assert private_api.request("start", body="x" * 600)[0] == 400
    assert private_api.request("start", headers={"Content-Type": "text/plain"})[0] == 400
    assert private_api.request("end", "invalid-id")[0] == 400
    assert private_api.request("end", str(uuid4()))[0] == 409
    assert private_api.request("start", path="/api/test/scenarios")[0] == 404
    assert not redis_client.exists(CONTROL_KEY)


def test_private_pages_and_assets_are_scoped_to_build_directory(redis_client, tmp_path):
    (tmp_path / "index.html").write_text("private page")
    (tmp_path / "_astro").mkdir()
    (tmp_path / "_astro" / "app.js").write_text("// private asset")
    places = tmp_path / "assets/accounts/philippine-places.json"
    places.parent.mkdir(parents=True)
    places.write_text('[{"name":"Fixture place"}]')
    (tmp_path / "private.json").write_text('"private"')
    with private_http(RedisSessionStore(redis_client), tmp_path) as api:
        for path, content_type in (("/", "text/html"), ("/_astro/app.js", "text/javascript")):
            with urlopen(api.url + path) as response:
                assert response.status == 200
                assert response.headers["Content-Type"] == content_type
                assert response.headers["X-Frame-Options"] == "DENY"
        assert api.request(path="/_astro/../../outside.txt")[0] == 404
        assert api.request(path="/runtime.py")[0] == 404
        with urlopen(api.url + "/assets/accounts/philippine-places.json") as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "application/json"
            assert response.headers["Cache-Control"] == "no-store"
            assert response.read() == places.read_bytes()
        assert (
            api.request(
                path="/assets/accounts/philippine-places.json", headers={"Host": "public.invalid"}
            )[0]
            == 403
        )
        assert api.request(path="/assets/accounts/../../private.json")[0] == 404
        assert api.request(path="/private.json")[0] == 404
