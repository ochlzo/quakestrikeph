from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from quakestrike.domain.features import FEATURE_NAMES
from quakestrike.domain.prediction import InvalidPredictionOutput, compose_forecast
from quakestrike.infrastructure.models.seis import SeisModel
from quakestrike.prediction_worker import worker


class FakeRoute:
    def __init__(self, value: float) -> None:
        self.value = value
        self.seen: list[float] = []

    def predict(self, rows, **kwargs):
        self.seen = rows[0]
        return [self.value]


def test_seis_uses_manifest_order_and_postprocesses_quantiles() -> None:
    features = dict(zip(reversed(FEATURE_NAMES), range(10), strict=True))
    features["anchor_time_is_minute_precision"] = 1
    values = {
        "m1_probability": 0.6,
        "m4_given_m1": 0.4,
        "m5_given_m4": 0.25,
        "expected_count": 2.0,
        "radius_median": 20.0,
        "maximum_q05": 3.0,
        "maximum_q50": 0.5,
        "maximum_q95": 2.0,
    }
    model = object.__new__(SeisModel)
    routes = {name: FakeRoute(value) for name, value in values.items()}
    model.routes = {
        name: ("catboost", route, FEATURE_NAMES, "quantile") for name, route in routes.items()
    }

    output = compose_forecast(model.predict(features), datetime(2026, 9, 24, tzinfo=UTC))

    assert all(
        route.seen == [features[name] for name in FEATURE_NAMES] for route in routes.values()
    )
    assert (
        output.maximum_magnitude_q05_24h,
        output.maximum_magnitude_q50_24h,
        output.maximum_magnitude_q95_24h,
    ) == (1.0, 2.0, 3.0)
    assert output.probability_m4_plus_24h == pytest.approx(0.24)
    assert output.probability_m5_plus_24h == pytest.approx(0.06)
    routes["maximum_q05"].value = float("nan")
    with pytest.raises(InvalidPredictionOutput):
        model.predict(features)


def test_changed_artifact_stops_worker_before_claim(monkeypatch) -> None:
    class ChangedModel(SeisModel):
        def verify_artifacts(self) -> None:
            raise ValueError("changed")

    class ExitWorker(Exception):
        pass

    def exit_worker(code: int) -> None:
        assert code == 2
        raise ExitWorker

    def create_app(settings, *, command_handler):
        return SimpleNamespace(worker_main=lambda _: command_handler({}))

    monkeypatch.setattr(worker, "create_prediction_app", create_app)
    monkeypatch.setattr(worker.os, "_exit", exit_worker)
    monkeypatch.setattr(
        worker,
        "process_prediction_delivery",
        lambda *args: pytest.fail("An unhealthy worker must not claim a prediction job."),
    )

    with pytest.raises(ExitWorker):
        worker.run_prediction(SimpleNamespace(log_level="INFO"), model=object.__new__(ChangedModel))
