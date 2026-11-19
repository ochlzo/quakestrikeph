import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection
from threading import Event, Thread

import pytest

from quakestrike.domain.features import HISTORY_WINDOW, HistoryCoverage
from quakestrike.forecast_simulation.catalog import CatalogStatus, catalog_status
from quakestrike.forecast_simulation.quota import QuotaUnavailable
from quakestrike.forecast_simulation.runtime import SimulationServer
from quakestrike.forecast_simulation.service import Simulator
from quakestrike.infrastructure.models.deterministic_test import DeterministicTestModel

NOW = datetime(2026, 11, 19, tzinfo=UTC)
SCENARIO = {"latitude": 14.6, "longitude": 120.9, "magnitude": 5.2, "depthKm": 18}


@pytest.mark.parametrize(
    ("gap", "expected"),
    [(timedelta(0), "current"), (timedelta(microseconds=1), "insufficient_history")],
)
def test_cutoff_requires_continuous_history(gap: timedelta, expected: str) -> None:
    join = NOW - timedelta(days=1)
    verified = [
        HistoryCoverage(NOW - HISTORY_WINDOW, join, True),
        HistoryCoverage(join + gap, NOW, True),
        HistoryCoverage(NOW - HISTORY_WINDOW, NOW, False),
    ]
    assert catalog_status(verified, NOW).status == expected


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(days=1), "current"),
        (timedelta(days=1, microseconds=1), "stale"),
        (timedelta(weeks=7), "stale"),
        (timedelta(weeks=7, microseconds=1), "too_old"),
    ],
)
def test_catalog_age_boundaries(age: timedelta, expected: str) -> None:
    cutoff = NOW - age
    verified = HistoryCoverage(cutoff - HISTORY_WINDOW, cutoff, True)
    assert catalog_status([verified], NOW) == CatalogStatus(expected, cutoff)


class Catalog:
    status = CatalogStatus("current", NOW)

    def read(self, now, scenario=None):
        return self.status, {"anchor_magnitude": scenario["magnitude"]} if scenario else None


class Quota:
    def __init__(self):
        self.starts = 0
        self.unavailable = False

    def admit(self, guest_id, client_ip):
        if self.unavailable:
            raise QuotaUnavailable
        self.starts += 1
        return None


def test_run_distinguishes_catalog_and_quota_errors_without_charging() -> None:
    catalog, quota = Catalog(), Quota()
    simulation = Simulator(catalog, quota, [DeterministicTestModel()])
    catalog.status = CatalogStatus("insufficient_history", None)
    assert (
        simulation.run(SCENARIO, "guest", "192.0.2.1").body["error"]["code"]
        == "SIMULATION_HISTORY_INSUFFICIENT"
    )
    catalog.status = CatalogStatus("too_old", NOW)
    assert (
        simulation.run(SCENARIO, "guest", "192.0.2.1").body["error"]["code"]
        == "SIMULATION_HISTORY_TOO_OLD"
    )
    catalog.status = CatalogStatus("current", NOW)
    quota.unavailable = True
    assert (
        simulation.run(SCENARIO, "guest", "192.0.2.1").body["error"]["code"]
        == "SIMULATION_QUOTA_UNAVAILABLE"
    )
    assert quota.starts == 0
    quota.unavailable = False
    result = simulation.run(SCENARIO, "guest", "192.0.2.1")
    assert result.status == 200
    assert result.body["scenario"] == SCENARIO
    assert result.body["catalogCutoff"] == "2026-11-19T00:00:00Z"
    assert result.body["forecast"]["windowEnd"] == "2026-11-20T00:00:00Z"
    assert quota.starts == 1


def test_capacity_is_held_during_inference_and_a_model_failure_is_charged() -> None:
    started, release = Event(), Event()

    class FailingModel:
        def predict(self, features):
            started.set()
            assert release.wait(timeout=5)
            raise ValueError("Model failure")

    quota = Quota()
    simulation = Simulator(Catalog(), quota, [FailingModel()])
    with ThreadPoolExecutor(1) as executor:
        first = executor.submit(simulation.run, SCENARIO, "guest", "192.0.2.1")
        try:
            assert started.wait(timeout=5)
            second = simulation.run(SCENARIO, "other", "192.0.2.2")
            assert second.status == 503
            assert second.body["error"]["code"] == "SIMULATION_BUSY"
            assert quota.starts == 1
        finally:
            release.set()
        assert first.result(timeout=5).body["error"]["code"] == "SIMULATION_MODEL_FAILED"
    assert quota.starts == 1


def test_disconnect_after_model_start_keeps_quota_and_capacity() -> None:
    started, release, completed = Event(), Event(), Event()

    class WaitingModel:
        def predict(self, features):
            started.set()
            assert release.wait(timeout=5)
            output = DeterministicTestModel().predict(features)
            completed.set()
            return output

    quota = Quota()
    simulation = Simulator(Catalog(), quota, [WaitingModel()])
    with SimulationServer(("127.0.0.1", 0), simulation, "test-token") as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        client = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            client.request(
                "POST",
                "/run",
                json.dumps({"scenario": SCENARIO, "guestId": "guest", "clientIp": "192.0.2.1"}),
                {"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            )
            assert started.wait(timeout=5)
            client.close()
            assert simulation.run(SCENARIO, "other", "192.0.2.2").status == 503
            release.set()
            assert completed.wait(timeout=5)
            assert quota.starts == 1
        finally:
            client.close()
            release.set()
            server.shutdown()
            thread.join(timeout=5)
