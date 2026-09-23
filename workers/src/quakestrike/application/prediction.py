"""Execute one fenced prediction job using supplied persistence and model adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from quakestrike.domain.prediction import ForecastOutput, InvalidPredictionOutput, compose_forecast


class StalePredictionAttempt(RuntimeError):
    """The execution token or its lease no longer owns the job."""


@dataclass(frozen=True, slots=True)
class PredictionClaim:
    job_id: UUID
    attempt_id: UUID
    execution_id: UUID
    event_time: datetime
    features: Mapping[str, object]


class PredictionStore(Protocol):
    def claim(
        self, dispatch_id: UUID, job_id: UUID, correlation_id: UUID
    ) -> PredictionClaim | None: ...

    def complete(self, claim: PredictionClaim, output: ForecastOutput) -> UUID | None: ...

    def fail(self, claim: PredictionClaim, code: str, message: str) -> None: ...


class PredictionModel(Protocol):
    def predict(self, features: Mapping[str, object]) -> Mapping[str, object]: ...


class ExecutePrediction:
    def __init__(self, store: PredictionStore, model: PredictionModel) -> None:
        self._store = store
        self._model = model

    def execute(self, dispatch_id: UUID, job_id: UUID, correlation_id: UUID) -> str:
        claim = self._store.claim(dispatch_id, job_id, correlation_id)
        if claim is None:
            return "unclaimed"
        try:
            try:
                output = compose_forecast(self._model.predict(claim.features), claim.event_time)
            except InvalidPredictionOutput:
                self._store.fail(
                    claim, "invalid_output", "The model output violates the forecast contract."
                )
                return "failed"
            except Exception:
                self._store.fail(
                    claim, "model_runtime_error", "The prediction model could not finish."
                )
                return "failed"
            return "succeeded" if self._store.complete(claim, output) is not None else "failed"
        except StalePredictionAttempt:
            return "stale"
