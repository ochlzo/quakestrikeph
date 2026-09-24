"""Execute one fenced prediction job using supplied persistence and model adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
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

    def fail(
        self, claim: PredictionClaim, code: str, message: str, *, retryable: bool = False
    ) -> str: ...


class PredictionModel(Protocol):
    def predict(self, features: Mapping[str, object]) -> Mapping[str, object]: ...


class ExecutePrediction:
    def __init__(
        self,
        store: PredictionStore,
        model: PredictionModel,
        *,
        on_claim: Callable[[PredictionClaim], None] | None = None,
    ) -> None:
        self._store = store
        self._model = model
        self._on_claim = on_claim

    def execute(self, dispatch_id: UUID, job_id: UUID, correlation_id: UUID) -> str:
        claim = self._store.claim(dispatch_id, job_id, correlation_id)
        if claim is None:
            return "unclaimed"
        if self._on_claim is not None:
            self._on_claim(claim)
        try:
            try:
                output = compose_forecast(self._model.predict(claim.features), claim.event_time)
            except InvalidPredictionOutput:
                self._store.fail(
                    claim, "invalid_output", "The model output violates the forecast contract."
                )
                return "failed"
            except Exception:
                return self._store.fail(
                    claim,
                    "model_runtime_error",
                    "The prediction model could not finish.",
                    retryable=True,
                )
            try:
                completed = self._store.complete(claim, output)
            except StalePredictionAttempt:
                raise
            except Exception:
                return self._store.fail(
                    claim,
                    "persistence_error",
                    "The prediction result could not be saved.",
                    retryable=True,
                )
            return "succeeded" if completed is not None else "failed"
        except StalePredictionAttempt:
            return "stale"
