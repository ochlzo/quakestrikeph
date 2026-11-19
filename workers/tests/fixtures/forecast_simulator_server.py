"""Run the real simulator with controlled model execution in disposable Compose."""

import os
from collections.abc import Mapping
from datetime import datetime
from urllib.parse import urlsplit

from redis import Redis
from sqlalchemy import create_engine

from quakestrike.forecast_simulation.catalog import SimulationCatalog
from quakestrike.forecast_simulation.quota import SimulationQuota
from quakestrike.forecast_simulation.runtime import SimulationServer
from quakestrike.forecast_simulation.service import Simulator
from quakestrike.infrastructure.logging.json_logging import configure_logging
from quakestrike.infrastructure.models.deterministic_test import DeterministicTestModel

TOKEN = "a1" * 32
QUOTA_USER = "forecast-simulator-test"
MODEL_STARTED = "forecast-simulation-test:model-started"
MODEL_RELEASE = "forecast-simulation-test:model-release"
CATALOG_NOW = "forecast-simulation-test:catalog-now"


class ControlledModel(DeterministicTestModel):
    def __init__(self, controls: Redis) -> None:
        self.controls = controls

    def predict(self, features: Mapping[str, object]) -> Mapping[str, object]:
        magnitude = features["anchor_magnitude"]
        if magnitude == 9.1:
            raise ValueError("Controlled model failure")
        if magnitude == 9.2:
            self.controls.rpush(MODEL_STARTED, "started")
            if self.controls.blpop(MODEL_RELEASE, timeout=10) is None:
                raise TimeoutError("The acceptance test did not release the model")
        return {
            **super().predict(features),
            "expected_count": features["catalog_m1_plus_count_past_7d"],
        }


def main() -> None:
    database_url = os.environ["TEST_SIMULATION_DATABASE_URL"]
    redis_url = os.environ["TEST_REDIS_URL"]
    database = urlsplit(database_url)
    if (
        database.hostname != "postgres-test"
        or database.path != "/quakestrike_test"
        or database.username != "quakestrike_simulator"
        or urlsplit(redis_url).hostname != "redis-test"
    ):
        raise ValueError("Requires the disposable Compose services")

    configure_logging("forecast-simulator")
    engine = create_engine(database_url)
    with Redis.from_url(redis_url) as controls:

        def catalog_now() -> datetime:
            value = controls.get(CATALOG_NOW)
            if not isinstance(value, bytes):
                raise RuntimeError("The acceptance test must set the catalog clock")
            return datetime.fromisoformat(value.decode("ascii"))

        controls.execute_command(
            "ACL",
            "SETUSER",
            QUOTA_USER,
            "reset",
            "on",
            ">integration-only",
            "~forecast-simulation:*",
            "+ping",
            "+eval",
            "+time",
            "+zremrangebyscore",
            "+zcard",
            "+zrange",
            "+zadd",
            "+pexpire",
        )
        with Redis.from_url(
            redis_url, username=QUOTA_USER, password="integration-only", socket_timeout=2
        ) as quota_redis:
            service = Simulator(
                SimulationCatalog(engine, None),
                SimulationQuota(quota_redis, bytes.fromhex(TOKEN)),
                [ControlledModel(controls), ControlledModel(controls)],
                now=catalog_now,
            )
            with SimulationServer(("0.0.0.0", 4350), service, TOKEN) as server:
                server.serve_forever()


if __name__ == "__main__":
    main()
