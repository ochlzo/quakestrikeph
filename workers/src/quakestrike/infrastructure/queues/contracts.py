"""Validated Python bindings for the versioned queue message schemas."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    message_version: Literal[1] = 1
    dispatch_id: UUID
    correlation_id: UUID

    def to_message(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class IngestionCommandV1(_Command):
    """Command consumed by the Data Ingestor."""

    run_id: UUID


class PredictionCommandV1(_Command):
    """Command consumed by the deferred Prediction Worker."""

    job_id: UUID


def parse_ingestion_command(payload: Mapping[str, object]) -> IngestionCommandV1:
    return IngestionCommandV1.model_validate(payload)


def parse_prediction_command(payload: Mapping[str, object]) -> PredictionCommandV1:
    return PredictionCommandV1.model_validate(payload)
