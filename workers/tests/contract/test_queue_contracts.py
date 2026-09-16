from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from quakestrike.infrastructure.queues.contracts import (
    IngestionCommandV1,
    PredictionCommandV1,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
QUEUE_CONTRACTS = REPOSITORY_ROOT / "packages" / "contracts" / "queue"


def load_schema(name: str) -> dict[str, object]:
    return json.loads((QUEUE_CONTRACTS / name).read_text(encoding="utf-8"))


def test_ingestion_binding_matches_v1_schema() -> None:
    command = IngestionCommandV1(
        dispatch_id=uuid4(),
        run_id=uuid4(),
        correlation_id=uuid4(),
    )
    payload = command.to_message()
    schema = load_schema("ingestion-command.v1.schema.json")

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(
        payload
    )
    assert payload["message_version"] == 1
    assert set(payload) == {"message_version", "dispatch_id", "run_id", "correlation_id"}


def test_prediction_binding_matches_v1_schema() -> None:
    command = PredictionCommandV1(
        dispatch_id=uuid4(),
        job_id=uuid4(),
        correlation_id=uuid4(),
    )
    payload = command.to_message()
    schema = load_schema("prediction-command.v1.schema.json")

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(
        payload
    )
    assert payload["message_version"] == 1
    assert set(payload) == {"message_version", "dispatch_id", "job_id", "correlation_id"}


@pytest.mark.parametrize("model", [IngestionCommandV1, PredictionCommandV1])
def test_queue_bindings_reject_unknown_fields_and_wrong_versions(model: type[object]) -> None:
    payload = {
        "message_version": 2,
        "dispatch_id": str(uuid4()),
        "run_id": str(uuid4()),
        "job_id": str(uuid4()),
        "correlation_id": str(uuid4()),
        "full_event_payload": "must-not-cross-the-queue",
    }

    with pytest.raises(ValidationError):
        model.model_validate(payload)  # type: ignore[attr-defined]
