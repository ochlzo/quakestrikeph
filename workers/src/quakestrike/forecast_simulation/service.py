"""Run guest forecasts without creating earthquake, forecast, or dispatch records."""

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from queue import Empty, LifoQueue
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from quakestrike.domain.prediction import compose_forecast
from quakestrike.forecast_simulation.catalog import CatalogStatus, utc_timestamp
from quakestrike.forecast_simulation.quota import QuotaOutcomeUnknown, QuotaUnavailable
from quakestrike.infrastructure.logging.json_logging import log_exception_event

_LOG = logging.getLogger("forecast-simulator.service")


class CatalogReader(Protocol):
    def read(
        self, now: datetime, scenario: Mapping[str, float] | None = None
    ) -> tuple[CatalogStatus, Mapping[str, object] | None]: ...


class Quota(Protocol):
    def admit(self, guest_id: str, client_ip: str) -> tuple[datetime, int] | None: ...


class Model(Protocol):
    def predict(self, features: Mapping[str, object]) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    body: Mapping[str, object]
    headers: Mapping[str, str] = field(default_factory=dict)


def rejection(status: int, code: str, message: str, **details: str) -> Response:
    return Response(status, {"error": {"code": code, "message": message, **details}})


class Simulator:
    def __init__(
        self,
        catalog: CatalogReader,
        quota: Quota,
        models: Iterable[Model],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.catalog = catalog
        self.quota = quota
        self.now = now
        self.models: LifoQueue[Model] = LifoQueue()
        for model in models:
            self.models.put_nowait(model)
        if self.models.empty():
            raise ValueError("The simulator requires at least one model slot.")

    def read_catalog(self) -> Response:
        try:
            catalog, _ = self.catalog.read(self.now())
        except SQLAlchemyError:
            return self._catalog_unavailable()
        return Response(200, catalog.public_status())

    def run(self, scenario: Mapping[str, float], guest_id: str, client_ip: str) -> Response:
        try:
            model = self.models.get_nowait()
        except Empty:
            return rejection(503, "SIMULATION_BUSY", "All simulation slots are busy.")
        try:
            return self._run(model, scenario, guest_id, client_ip)
        finally:
            self.models.put_nowait(model)

    def _run(
        self, model: Model, scenario: Mapping[str, float], guest_id: str, client_ip: str
    ) -> Response:
        try:
            catalog, features = self.catalog.read(self.now(), scenario)
        except SQLAlchemyError:
            return self._catalog_unavailable()
        cutoff = catalog.cutoff
        if cutoff is None:
            return rejection(
                503,
                "SIMULATION_HISTORY_INSUFFICIENT",
                "Seven continuous days of verified PHIVOLCS records are unavailable.",
            )
        if catalog.status == "too_old":
            return rejection(
                503,
                "SIMULATION_HISTORY_TOO_OLD",
                "The latest qualifying PHIVOLCS cutoff is more than seven weeks old.",
                catalogCutoff=utc_timestamp(cutoff),
            )
        assert features is not None
        try:
            retry = self.quota.admit(guest_id, client_ip)
        except QuotaUnavailable:
            return rejection(
                503, "SIMULATION_QUOTA_UNAVAILABLE", "Simulation limits could not be checked."
            )
        except QuotaOutcomeUnknown:
            return rejection(
                504,
                "SIMULATION_OUTCOME_UNKNOWN",
                "The run timed out before its outcome could be confirmed.",
            )
        if retry is not None:
            deadline, seconds = retry
            return Response(
                429,
                {
                    "error": {
                        "code": "SIMULATION_LIMIT_REACHED",
                        "message": "Simulation limit reached.",
                        "retryAt": utc_timestamp(deadline),
                    }
                },
                {"Retry-After": str(seconds)},
            )

        # Quota admission is the start boundary. A lost client never interrupts this call.
        try:
            output = compose_forecast(model.predict(features), cutoff)
        except Exception as error:
            log_exception_event(
                _LOG,
                logging.ERROR,
                "Simulation model execution failed.",
                event_code="simulation_model_failed",
                error=error,
            )
            return rejection(
                500,
                "SIMULATION_MODEL_FAILED",
                "The model started but could not complete the forecast.",
            )
        return Response(
            200,
            {
                "scenario": scenario,
                "catalogCutoff": utc_timestamp(cutoff),
                "forecast": {
                    "windowStart": utc_timestamp(output.window_start),
                    "windowEnd": utc_timestamp(output.window_end),
                    "probabilityM1Plus24h": output.probability_m1_plus_24h,
                    "probabilityM4Plus24h": output.probability_m4_plus_24h,
                    "probabilityM5Plus24h": output.probability_m5_plus_24h,
                    "expectedM1PlusCount24h": output.expected_m1_plus_count_24h,
                    "maximumMagnitudeQ05_24h": output.maximum_magnitude_q05_24h,
                    "maximumMagnitudeQ50_24h": output.maximum_magnitude_q50_24h,
                    "maximumMagnitudeQ95_24h": output.maximum_magnitude_q95_24h,
                    "activityRadiusMedianKm24h": output.activity_radius_median_km_24h,
                },
            },
        )

    @staticmethod
    def _catalog_unavailable() -> Response:
        return rejection(
            503, "SIMULATION_CATALOG_UNAVAILABLE", "The PHIVOLCS catalog could not be checked."
        )
