import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from quakestrike.application.dispatch import AlertDispatch
from quakestrike.infrastructure.queues.alert_publisher import CeleryAlertPublisher
from quakestrike.infrastructure.queues.contracts import AlertCommandV1


def test_alert_publisher_emits_only_versioned_durable_identifiers():
    calls = []

    class Broker:
        def send_task(self, name, **options):
            calls.append((name, options))

    dispatch = AlertDispatch(uuid4(), uuid4(), uuid4())
    CeleryAlertPublisher(Broker()).publish(dispatch)
    assert calls == [
        (
            "quakestrike.infrastructure.queues.tasks.publish_alert",
            {
                "args": [
                    {
                        "message_version": 1,
                        "dispatch_id": str(dispatch.dispatch_id),
                        "alert_job_id": str(dispatch.alert_job_id),
                        "correlation_id": str(dispatch.correlation_id),
                    }
                ],
                "queue": "alert",
            },
        )
    ]
    assert (
        AlertCommandV1.model_validate(calls[0][1]["args"][0]).alert_job_id == dispatch.alert_job_id
    )


def test_alert_contract_schema_matches_model_and_rejects_extra_content():
    schema_path = (
        Path(__file__).resolve().parents[3]
        / "packages/contracts/queue/alert-command.v1.schema.json"
    )
    validator = Draft202012Validator(
        json.loads(schema_path.read_text()), format_checker=FormatChecker()
    )
    payload = {
        "message_version": 1,
        "dispatch_id": "b45b7c54-f86f-4182-a510-7b69f3ca675f",
        "alert_job_id": "3fd434db-fefc-408c-bc5a-1d54fbe7ef03",
        "correlation_id": "ab73f5d3-4fba-421a-887f-ea4f7a3a67d2",
    }
    validator.validate(payload)
    AlertCommandV1.model_validate(payload)
    for changed in (
        {**payload, "message_version": 2},
        {**payload, "message": "forbidden"},
        {**payload, "alert_job_id": "bad"},
    ):
        assert list(validator.iter_errors(changed))
        with pytest.raises(ValidationError):
            AlertCommandV1.model_validate(changed)
