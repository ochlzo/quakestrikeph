from uuid import uuid4

import pytest

from quakestrike.alert_testing.application.scenarios import Scenarios
from quakestrike.alert_testing.application.sessions import Sessions
from quakestrike.alert_testing.application.submissions import Submissions
from quakestrike.alert_testing.application.workspaces import Workspaces
from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.infrastructure.deliveries import RedisDeliveryStore
from quakestrike.alert_testing.infrastructure.preparation import PreparationSigner, canonical
from quakestrike.alert_testing.infrastructure.redis import CONTROL_KEY, PREFIX, RedisSessionStore
from quakestrike.alert_testing.infrastructure.workspaces import RedisWorkspaceStore

from .test_alert_testing_scenarios import inputs as inputs_fixture
from .test_alert_testing_sessions import redis_client as redis_fixture

pytestmark = pytest.mark.integration
redis_client = redis_fixture
inputs = inputs_fixture


def test_workspace_autosave_preview_restore_and_separate_submission(redis_client, inputs):
    sessions = Sessions(RedisSessionStore(redis_client))
    session = sessions.start()
    owner, tab, other = session["session_id"], str(uuid4()), str(uuid4())
    signer = PreparationSigner("a" * 64)
    store = RedisWorkspaceStore(redis_client, "https://example.invalid")
    workspaces = Workspaces(sessions, store, signer)
    assert workspaces.read(owner, tab)["missing"]
    invalid = {**inputs, "magnitude": ""}
    workspaces.save(owner, tab, 0, invalid, [], None)
    assert workspaces.read(owner, tab)["inputs"]["magnitude"] == ""
    prepared = Scenarios(sessions, signer=signer).prepare(owner, inputs)
    tester = str(uuid4())
    result = workspaces.save(owner, tab, 1, inputs, [tester], prepared)
    assert result["preview_url"].endswith(f"/forecasts/{prepared['event_id']}?test=true")
    assert workspaces.read(owner, tab)["prepared"] == canonical(prepared)
    assert workspaces.read(owner, tab)["selected"] == [tester]
    assert workspaces.read(owner, other)["missing"]
    # Repeating a save after a lost response is safe.
    assert workspaces.save(owner, tab, 1, inputs, [tester], prepared) == result
    with pytest.raises(ValueError):
        workspaces.save(owner, tab, 1, inputs, [], prepared)
    keys = redis_client.keys(f"{PREFIX}{owner}:*")
    assert not any(
        ":job:" in key or key.endswith(":history") or key.endswith(":queue") for key in keys
    )
    preview_key = f"{PREFIX}{owner}:preview:{prepared['event_id']}"
    original = redis_client.get(preview_key)
    workspaces.save(owner, tab, 2, inputs, [], prepared)
    assert redis_client.get(preview_key) == original
    assert redis_client.pttl(preview_key) > 0
    submissions = Submissions(
        sessions, RedisDeliveryStore(redis_client, "https://example.invalid"), signer
    )
    submitted = submissions.submit(owner, inputs, prepared, [tester])
    assert submitted["event_id"] == prepared["event_id"]
    assert submissions.submit(owner, inputs, prepared, [tester]) == submitted
    sessions.end(owner)
    with pytest.raises(SessionConflict):
        workspaces.read(owner, tab)
    assert not redis_client.keys(f"{PREFIX}{owner}:*")


def test_workspace_expiry_and_invalid_preparation_are_rejected(redis_client, inputs):
    sessions = Sessions(RedisSessionStore(redis_client))
    owner, tab = sessions.start()["session_id"], str(uuid4())
    signer = PreparationSigner("a" * 64)
    workflow = Workspaces(
        sessions, RedisWorkspaceStore(redis_client, "https://example.invalid"), signer
    )
    prepared = Scenarios(sessions, signer=signer).prepare(owner, inputs)
    with pytest.raises(ValueError):
        workflow.save(owner, tab, 0, inputs, [], {**prepared, "event_id": str(uuid4())})
    assert workflow.read(owner, tab)["missing"]
    redis_client.hset(CONTROL_KEY, "expires_at_ms", "1")
    with pytest.raises(SessionConflict):
        workflow.save(owner, tab, 0, inputs, [], None)
    with pytest.raises(SessionConflict):
        workflow.read(owner, tab)
