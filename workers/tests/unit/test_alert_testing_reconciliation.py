import io
import json
from unittest.mock import Mock
from uuid import uuid4

import pytest

from quakestrike.alert_testing.application.reconciliation import Reconciliation
from quakestrike.alert_testing.consumer_runtime import PollingDiagnostics
from quakestrike.application.sms_polling import SmsOutcome
from quakestrike.infrastructure.logging.json_logging import configure_logging


@pytest.mark.parametrize(
    "error",
    ["provider_credentials_or_credit"],
)
def test_poll_failure_is_bounded_private_and_recovers_only_on_verified_response(error):
    event, attempt = str(uuid4()), str(uuid4())
    private = "secret reference destination@example.invalid message body redis://secret"
    stream = io.StringIO()
    reporter = PollingDiagnostics(configure_logging("alert-testing-consumer", stream=stream))
    store, provider = Mock(), Mock()
    candidate = (event, {"attempt_id": attempt, "provider_reference": private})
    store.poll_candidate.side_effect = [candidate, candidate, None, candidate, candidate, None]
    provider.poll.side_effect = [
        SmsOutcome("unknown", error, {"payload": private}),
        SmsOutcome("unknown", error, {"error_message": private}),
        SmsOutcome("unknown"),
        SmsOutcome("accepted"),
    ]
    reconciliation = Reconciliation(store, provider, report=reporter)
    assert reconciliation.once("owner")
    failure = json.loads(stream.getvalue())
    assert failure["event_code"] == "alert_testing_sms_poll_unavailable"
    assert failure["service"] == "alert-testing-consumer"
    assert failure["context"] == {
        "operation": "sms_status",
        "provider": "iprog",
        "event_id": event,
        "job_id": event,
        "attempt_id": attempt,
        "reason": error,
    }
    assert reconciliation.once("owner")
    assert not reconciliation.once("owner")
    assert reconciliation.once("owner")
    assert len(stream.getvalue().splitlines()) == 1
    store.reconcile_sms.assert_not_called()
    assert reconciliation.once("owner")
    recovery = json.loads(stream.getvalue().splitlines()[1])
    assert recovery["event_code"] == "alert_testing_sms_poll_recovered"
    assert recovery["context"]["reason"] == error
    store.reconcile_sms.assert_called_once()
    assert not reconciliation.once("owner")
    assert len(stream.getvalue().splitlines()) == 2
    assert all(
        value not in stream.getvalue()
        for value in (
            "secret reference",
            "destination@example.invalid",
            "message body",
            "redis://secret",
        )
    )
    provider.submit.assert_not_called()


def test_exceptions_and_unrecognized_errors_are_sanitized_and_normal_unknown_is_quiet():
    event, attempt = str(uuid4()), str(uuid4())
    private = "PRIVATE_SECRET reference destination@example.invalid payload"
    stream = io.StringIO()
    reporter = PollingDiagnostics(configure_logging("alert-testing-consumer", stream=stream))
    store, provider = Mock(), Mock()
    store.poll_candidate.return_value = (
        event,
        {"attempt_id": attempt, "provider_reference": private},
    )
    provider.poll.side_effect = [
        SmsOutcome("unknown"),
        RuntimeError(private),
        RuntimeError(private),
        SmsOutcome("unknown", "provider_credentials_or_credit"),
        SmsOutcome("failed", "provider_rejected"),
        SmsOutcome("unknown", private),
        SmsOutcome("unknown", private),
        SmsOutcome("delivered"),
    ]
    reconciliation = Reconciliation(store, provider, report=reporter)
    assert reconciliation.once("owner")
    assert not stream.getvalue()
    for _ in range(7):
        assert reconciliation.once("owner")
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [record["event_code"] for record in records] == [
        "alert_testing_sms_poll_unavailable",
        "alert_testing_sms_poll_recovered",
        "alert_testing_sms_poll_unavailable",
        "alert_testing_sms_poll_recovered",
    ]
    assert [record["context"]["reason"] for record in records] == [
        "provider_transport_uncertain",
        "provider_transport_uncertain",
        "provider_failure",
        "provider_failure",
    ]
    assert all(
        value not in stream.getvalue()
        for value in ("PRIVATE_SECRET", "destination@example.invalid", "payload")
    )
    assert store.reconcile_sms.call_count == 2
    provider.submit.assert_not_called()
