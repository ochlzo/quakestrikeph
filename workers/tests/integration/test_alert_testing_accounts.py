import json
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import ProgrammingError

from quakestrike.alert_testing.application.sessions import Sessions
from quakestrike.alert_testing.application.testers import Testers as AccountWorkflow
from quakestrike.alert_testing.infrastructure.accounts import PostgresAccountReader
from quakestrike.alert_testing.infrastructure.redis import CONTROL_KEY, PREFIX, RedisSessionStore
from quakestrike.alert_testing.interface.http import PrivateServer
from quakestrike.infrastructure.database.account_tables import users

from .test_alert_resolution import account
from .test_alert_testing_sessions import PrivateClient
from .test_alert_testing_sessions import redis_client as redis_fixture

pytestmark = pytest.mark.integration
redis_client = redis_fixture


@contextmanager
def api_server(redis_client, reader=None):
    sessions = Sessions(RedisSessionStore(redis_client))
    server = PrivateServer(
        sessions,
        Path("."),
        port=0,
        testers=AccountWorkflow(reader, sessions) if reader else None,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield PrivateClient(server), sessions
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.fixture
def restricted_accounts(migrated_engine):
    # Exercise the production column grant against a real, separate database login.
    source = Path("database/initialization/provision-roles.sh").read_text()
    block = source.split("  create-alert-testing)")[1].split("  create-observer)")[0]
    grant = "GRANT SELECT " + block.split("GRANT SELECT ")[1].split(";")[0] + ";"
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE ROLE quakestrike_alert_testing LOGIN NOINHERIT PASSWORD 'integration-only'"
            )
        )
        connection.execute(
            text("ALTER ROLE quakestrike_alert_testing SET default_transaction_read_only = on")
        )
        connection.execute(text("GRANT USAGE ON SCHEMA public TO quakestrike_alert_testing"))
        connection.execute(text(grant))
    engine = create_engine(
        migrated_engine.url.set(username="quakestrike_alert_testing", password="integration-only")
    )
    try:
        yield PostgresAccountReader(engine), engine
    finally:
        engine.dispose()
        with migrated_engine.begin() as connection:
            connection.execute(text("DROP OWNED BY quakestrike_alert_testing"))
            connection.execute(text("DROP ROLE quakestrike_alert_testing"))


def test_restricted_account_search_masks_fields_and_never_writes(
    redis_client,
    restricted_accounts,
    migrated_engine,
):
    reader, engine = restricted_accounts
    ids = [
        account(
            migrated_engine,
            display_name=f"Tester {number}",
            mobile_number=None,
            mobile_verified_at=None,
            sms_enabled=False,
            account_status="suspended" if number == 6 else "active",
            **({"onboarding_completed_at": None, "email_enabled": False} if number == 5 else {}),
        )
        for number in range(7)
    ]
    with migrated_engine.connect() as connection:
        before = connection.execute(select(users)).all()
    with api_server(redis_client, reader) as (api, _):
        owner = api.request("start")[1]["session_id"]
        body = {
            "session_id": owner,
            "query": "Tester",
            "selected": None,
            "page": 1,
            "size": 5,
            "event": {"magnitude": "5.2", "latitude": "9.86", "longitude": "125.55"},
        }
        code, response = api.request("search", path="/api/test/testers", body=body)
        assert code == 200 and response["total"] == 7 and len(response["accounts"]) == 5
        assert list(redis_client.scan_iter(match=PREFIX + "*")) == [CONTROL_KEY]
        assert api.request(path="/api/test/draft")[0] == 404
        assert api.request("save", path="/api/test/draft", body={})[0] == 404
        assert response["accounts"][0]["channels"]["email"]["eligible"]
        assert "clerk_user_id" not in json.dumps(response)
        assert "alert_location_latitude" not in json.dumps(response)
        assert str(ids[0]) + "@example.invalid" not in json.dumps(response)
        body.update(page=2, selected=[str(ids[6])])
        code, response = api.request("search", path="/api/test/testers", body=body)
        assert code == 200 and response["page"] == 1
        assert [item["id"] for item in response["accounts"]] == [str(ids[6])]
        assert response["accounts"][0]["status"] == "suspended"
        body.update(selected=[str(ids[5])])
        assert not api.request("search", path="/api/test/testers", body=body)[1]["accounts"][0][
            "onboarding_complete"
        ]
        body.update(query="%' OR true --", selected=None)
        assert api.request("search", path="/api/test/testers", body=body)[1]["total"] == 0
        body.update(query="Tester", size=500)
        assert api.request("search", path="/api/test/testers", body=body)[0] == 400
        assert (
            api.request(
                "search",
                path="/api/test/testers",
                body=body,
                headers={"Origin": "https://outside.invalid"},
            )[0]
            == 403
        )
        assert api.request("end", owner)[0] == 200
        body["size"] = 5
        assert api.request("search", path="/api/test/testers", body=body)[0] == 409
    for statement in (
        "UPDATE users SET display_name = 'changed'",
        "DELETE FROM users",
        "TRUNCATE users",
        "INSERT INTO users (display_name) VALUES ('changed')",
        "SELECT clerk_user_id FROM users",
        "SELECT * FROM alert_jobs",
        "CREATE TABLE forbidden (id int)",
    ):
        with engine.connect() as connection, pytest.raises(ProgrammingError):
            connection.execute(text("SET TRANSACTION READ WRITE"))
            connection.execute(text(statement))
    with migrated_engine.connect() as connection:
        assert connection.execute(select(users)).all() == before
        for table in (
            "alert_jobs",
            "alert_recipients",
            "alert_delivery_attempts",
            "job_dispatches",
        ):
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0
    with api_server(redis_client, PostgresAccountReader(migrated_engine)) as (api, _):
        owner = api.request("start")[1]["session_id"]
        body.update(session_id=owner, query="Tester", page=1)
        code, response = api.request("search", path="/api/test/testers", body=body)
        assert code == 503 and response == {
            "error": "dependency-unavailable",
            "dependency": "Accounts",
        }


def test_account_reads_require_active_ownership_and_recheck_closure(
    redis_client,
    restricted_accounts,
    migrated_engine,
):
    reader, _ = restricted_accounts
    account(migrated_engine, mobile_number=None, mobile_verified_at=None, sms_enabled=False)
    with api_server(redis_client, reader) as (api, sessions):
        body = {
            "session_id": str(uuid4()),
            "query": "",
            "selected": None,
            "page": 1,
            "size": 5,
            "event": {"magnitude": "5.2", "latitude": "9.86", "longitude": "125.55"},
        }
        assert api.request("search", path="/api/test/testers", body=body)[0] == 409
        owner = api.request("start")[1]["session_id"]
        body["session_id"] = owner
        assert api.request("search", path="/api/test/testers", body=body)[0] == 200
        redis_client.hset(CONTROL_KEY, "expires_at_ms", 1)
        assert api.request("search", path="/api/test/testers", body=body)[0] == 409
        assert api.request("cleanup", owner)[0] == 200
        owner = api.request("start")[1]["session_id"]
        assert api.request("search", path="/api/test/testers", body=body)[0] == 409
        body["session_id"] = owner

        class ClosingReader:
            def search(self, *args):
                result = reader.search(*args)
                sessions.end(owner)
                return result

        api.server.testers = AccountWorkflow(ClosingReader(), sessions)
        code, response = api.request("search", path="/api/test/testers", body=body)
        assert code == 409 and response == {"error": "session-conflict"}
        assert list(redis_client.scan_iter(match=PREFIX + "*")) == [CONTROL_KEY]
