import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from quakestrike.alert_testing.application.reconciliation import Reconciliation
from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.infrastructure.redis import CONTROL_KEY
from quakestrike.application.alert_delivery import SubmissionResult
from quakestrike.application.sms_polling import SmsOutcome

from .test_alert_testing_delivery import (
    inputs as inputs_fixture,
)
from .test_alert_testing_delivery import (
    prepare,
    request,
    submit,
    workflow,
)
from .test_alert_testing_delivery import (
    redis_client as redis_fixture,
)

pytestmark = pytest.mark.integration
inputs = inputs_fixture
redis_client = redis_fixture


def recipient(h, event, channel):
    slot = f"{h.accounts.account['user_id']}:{channel}"
    key = h.store.key(h.owner, f"recipients:{event}")
    return key, slot, json.loads(h.store.client.hget(key, slot))


@pytest.mark.parametrize("submission", ["accepted", "unknown", "permanent"])
@pytest.mark.parametrize("early_status", ["accepted", "failed", "delivered"])
def test_early_email_evidence_survives_submission_completion(
    redis_client, inputs, submission, early_status
):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        event = scenario["event_id"]
        submit(h, inputs, scenario)

        def callback(call):
            key, slot, row = recipient(h, event, "email")
            assert (
                redis_client.hget(h.store.key(h.owner, f"attempts:{event}"), row["token"]) == slot
            )
            assert call.attempt_id == f"test:{h.owner}:{event}:{row['token']}"
            row.update(
                status=early_status,
                reason="Provider confirmed delivery.",
                provider_reference="fake-email",
                provider_status_at_ms=1,
            )
            redis_client.hset(key, slot, json.dumps(row))
            redis_client.hset(
                h.store.key(h.owner, "references"), "email:fake-email", f"{event}:{row['token']}"
            )

        h.providers["email"].callback = callback
        h.providers["email"].outcome = SubmissionResult(submission, reference="fake-email")
        assert h.consumer.once(h.owner)
        row = recipient(h, event, "email")[2]
        assert row["status"] == early_status and row["provider_status_at_ms"] == 1
        assert request(h, "results", event_id=event)[1]["counts"][early_status] >= 1
        assert not h.consumer.once(h.owner)
        assert len(h.providers["email"].calls) == 1


def test_submission_reference_conflict_preserves_early_evidence(redis_client, inputs):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        event = scenario["event_id"]
        submit(h, inputs, scenario)

        def callback(_call):
            key, slot, row = recipient(h, event, "email")
            row.update(
                status="delivered", provider_reference="early-reference", provider_status_at_ms=1
            )
            redis_client.hset(key, slot, json.dumps(row))

        h.providers["email"].callback = callback
        h.consumer.once(h.owner)
        row = recipient(h, event, "email")[2]
        assert row["status"] == "delivered" and row["provider_reference"] == "early-reference"
        assert "conflict" in row["evidence_note"]


@pytest.mark.parametrize("initial", ["accepted", "unknown"])
def test_sms_poll_reconciles_known_references_without_resubmission(redis_client, inputs, initial):
    with workflow(redis_client) as h:
        h.providers["sms"].outcome = SubmissionResult(initial, reference="fake-sms")
        scenario = prepare(h, inputs)
        event = scenario["event_id"]
        submit(h, inputs, scenario)
        h.consumer.once(h.owner)
        calls = []
        poller = SimpleNamespace(
            poll=lambda reference: calls.append(reference) or SmsOutcome("delivered")
        )
        reconciliation = Reconciliation(h.store, poller)
        assert reconciliation.once(h.owner)
        assert calls == ["fake-sms"]
        row = recipient(h, event, "sms")[2]
        assert row["status"] == "delivered" and row["delivery_evidence"]
        assert "provider_status_at_ms" not in row
        assert not reconciliation.once(h.owner)
        assert h.store.reconcile_sms(h.owner, event, row, SmsOutcome("failed")) == ["ignored"]
        assert recipient(h, event, "sms")[2]["status"] == "delivered"
        assert len(h.providers["sms"].calls) == 1
        public = request(h, "results", event_id=event)[1]
        assert public["counts"]["delivered"] == 1 and public["counts"]["accepted"] == 1
        assert "fake-sms" not in json.dumps(public)


def test_unknown_sms_poll_postpones_retry_and_requires_known_reference(redis_client, inputs):
    with workflow(redis_client) as h:
        h.providers["sms"].outcome = SubmissionResult("unknown")
        scenario = prepare(h, inputs)
        submit(h, inputs, scenario)
        h.consumer.once(h.owner)
        calls = []
        reconciliation = Reconciliation(
            h.store, SimpleNamespace(poll=lambda reference: calls.append(reference))
        )
        assert not reconciliation.once(h.owner) and not calls
        event = scenario["event_id"]
        key, slot, row = recipient(h, event, "sms")
        row["provider_reference"] = "known-reference"
        h.store.finish(h.owner, event, row)
        reconciliation.provider.poll = lambda reference: (
            calls.append(reference) or SmsOutcome("unknown")
        )
        assert reconciliation.once(h.owner)
        assert not reconciliation.once(h.owner)
        assert calls == ["known-reference"]
        assert recipient(h, event, "sms")[2]["status"] == "unknown"
        assert redis_client.hget(key, slot)


def test_sms_reference_conflict_cannot_change_outcome(redis_client, inputs):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        event = scenario["event_id"]
        submit(h, inputs, scenario)
        h.consumer.once(h.owner)
        row = recipient(h, event, "sms")[2]
        redis_client.hset(h.store.key(h.owner, "references"), "sms:fake-sms", "another-attempt")
        assert h.store.reconcile_sms(h.owner, event, row, SmsOutcome("delivered")) == [
            "reference-conflict"
        ]
        assert recipient(h, event, "sms")[2]["status"] == "accepted"


@pytest.mark.parametrize("closure", ["end", "expiry"])
def test_closure_during_authorized_sms_poll_cannot_restore_history(redis_client, inputs, closure):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        event = scenario["event_id"]
        submit(h, inputs, scenario)
        h.consumer.once(h.owner)

        def poll(reference):
            assert reference == "fake-sms"
            if closure == "end":
                state = h.sessions.end(h.owner)
            else:
                redis_client.hset(CONTROL_KEY, "expires_at_ms", 1)
                state = h.sessions.read()
            assert state["closure_phase"] == "waiting"
            return SmsOutcome("delivered")

        reconciliation = Reconciliation(h.store, SimpleNamespace(poll=poll))
        with pytest.raises(SessionConflict):
            reconciliation.once(h.owner)
        assert recipient(h, event, "sms")[2]["status"] == "accepted"
        redis_client.hset(CONTROL_KEY, "calls_until_ms", 0)
        h.sessions.maintain()
        with pytest.raises(SessionConflict):
            reconciliation.once(h.owner)
        assert not list(redis_client.scan_iter(match=h.store.key(h.owner, "*")))


def test_sms_poll_outage_preserves_state_and_later_sweep_recovers(redis_client, inputs):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        event = scenario["event_id"]
        submit(h, inputs, scenario)
        h.consumer.once(h.owner)
        failures = []

        def poll(reference):
            failures.append(reference)
            raise RuntimeError("private provider exception")

        reconciliation = Reconciliation(h.store, SimpleNamespace(poll=poll))
        assert reconciliation.once(h.owner)
        assert not reconciliation.once(h.owner)
        assert recipient(h, event, "sms")[2]["status"] == "accepted"
        redis_client.zadd(
            h.store.key(h.owner, "sms-polls"), {f"{event}:{h.accounts.account['user_id']}:sms": 0}
        )
        reconciliation.provider.poll = lambda reference: SmsOutcome("delivered")
        assert reconciliation.once(h.owner)
        assert recipient(h, event, "sms")[2]["status"] == "delivered"
        assert len(h.providers["sms"].calls) == 1 and failures == ["fake-sms"]


def test_end_exposes_waiting_then_deletion_and_fences_interrupted_calls(redis_client, inputs):
    ordinary = f"ordinary:{uuid4()}"
    redis_client.rpush(ordinary, "production-command")
    try:
        with workflow(redis_client) as h:
            scenario = prepare(h, inputs)
            event = scenario["event_id"]
            submit(h, inputs, scenario)
            h.consumer.once(h.owner)
            row = recipient(h, event, "sms")[2]
            code, state = h.api.request("end", body={"session_id": h.owner})
            assert code == 200 and state["closure_phase"] == "waiting"
            assert 0 < state["calls_until_ms"] - state["server_time_ms"] <= 15000
            assert state["closed_at_ms"] and not state["cleanup_completed_at_ms"]
            assert request(h, "results", event_id=event)[0] == 409
            assert request(h, "submit", inputs=inputs, scenario=scenario, selected=[])[0] == 409
            with pytest.raises(SessionConflict):
                h.store.reconcile_sms(h.owner, event, row, SmsOutcome("delivered"))
            redis_client.hset(CONTROL_KEY, "calls_until_ms", 0)
            assert h.sessions.read()["closure_phase"] == "deleting"
            h.sessions.maintain()
            complete = h.sessions.read()
            assert complete["closure_phase"] == "complete"
            assert complete["cleanup_completed_at_ms"] >= complete["closed_at_ms"]
            assert not list(redis_client.scan_iter(match=h.store.key(h.owner, "*")))
            with pytest.raises(SessionConflict):
                h.store.finish(h.owner, event, row)
            assert h.sessions.start()["session_id"] != h.owner
            with pytest.raises(SessionConflict):
                h.store.reconcile_sms(h.owner, event, row, SmsOutcome("delivered"))
            assert redis_client.lrange(ordinary, 0, -1) == ["production-command"]
    finally:
        redis_client.delete(ordinary)


def test_expiry_keeps_only_bounded_closure_metadata_after_children_expire(redis_client, inputs):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        submit(h, inputs, scenario)
        h.consumer.once(h.owner)
        clock = redis_client.time()
        now = clock[0] * 1000 + clock[1] // 1000
        redis_client.hset(CONTROL_KEY, "expires_at_ms", now)
        for key in redis_client.scan_iter(match=h.store.key(h.owner, "*")):
            redis_client.pexpireat(key, now)
        state = h.sessions.read()
        assert state["status"] == "expired" and state["closure_phase"] == "waiting"
        ttl = redis_client.pttl(CONTROL_KEY)
        h.sessions.maintain()
        assert redis_client.pttl(CONTROL_KEY) <= ttl
        assert not list(redis_client.scan_iter(match=h.store.key(h.owner, "*")))
        redis_client.hset(CONTROL_KEY, "calls_until_ms", 0)
        h.sessions.maintain()
        assert h.sessions.read()["closure_phase"] == "complete"


def test_cleanup_failure_deletes_all_owned_indexes_on_idempotent_retry(
    redis_client, inputs, monkeypatch
):
    with workflow(redis_client) as h:
        scenario = prepare(h, inputs)
        submit(h, inputs, scenario)
        h.consumer.once(h.owner)
        redis_client.hset(CONTROL_KEY, "calls_until_ms", 0)
        unlink = redis_client.unlink
        monkeypatch.setattr(
            redis_client, "unlink", lambda *keys: (_ for _ in ()).throw(RedisError())
        )
        state = h.sessions.end(h.owner)
        assert state["status"] == "cleanup-failure" and state["closure_phase"] == "failed"
        h.sessions.maintain()
        assert h.sessions.read()["status"] == "cleanup-failure"
        assert h.api.request("start")[0] == 409
        monkeypatch.setattr(redis_client, "unlink", unlink)
        assert h.sessions.retry_cleanup(h.owner)["status"] == "ended"
        assert h.sessions.retry_cleanup(h.owner)["status"] == "ended"
        assert not list(redis_client.scan_iter(match=h.store.key(h.owner, "*")))
