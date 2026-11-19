"""Serve the simulator on the private Backend network."""

import json
import logging
import os
import re
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from sqlalchemy import create_engine

from quakestrike.forecast_simulation.catalog import BootstrapCoverage, SimulationCatalog
from quakestrike.forecast_simulation.quota import SimulationQuota
from quakestrike.forecast_simulation.service import Response, Simulator, rejection
from quakestrike.infrastructure.models.seis import SeisModel

_LOG = logging.getLogger(__name__)


class SimulationServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], service: Simulator, token: str) -> None:
        self.service = service
        self.authorization = f"Bearer {token}".encode("ascii")
        super().__init__(address, SimulationHandler)

    def get_request(self):
        client, address = super().get_request()
        client.settimeout(5)
        return client, address


class SimulationHandler(BaseHTTPRequestHandler):
    server: SimulationServer

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._write(Response(200, {"status": "ready"}))
        elif self.path == "/catalog" and self._authorized():
            self._handle(self.server.service.read_catalog)
        else:
            self._write(rejection(404, "NOT_FOUND", "Route not found."))

    def do_POST(self) -> None:
        if self.path != "/run" or not self._authorized():
            self._write(rejection(404, "NOT_FOUND", "Route not found."))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 8192:
                raise ValueError("Invalid request length")
            request = json.loads(self.rfile.read(length))
            scenario, guest, ip = request["scenario"], request["guestId"], request["clientIp"]
        except (ValueError, TypeError, KeyError, OSError):
            self._write(rejection(400, "INVALID_REQUEST", "Invalid simulator request."))
            return
        self._handle(lambda: self.server.service.run(scenario, guest, ip))

    def _handle(self, operation) -> None:
        try:
            response = operation()
        except Exception:
            _LOG.error("Simulation request failed.")
            response = rejection(500, "INTERNAL_ERROR", "Internal server error.")
        self._write(response)

    def _authorized(self) -> bool:
        return compare_digest(
            self.headers.get("Authorization", "").encode(), self.server.authorization
        )

    def _write(self, response: Response) -> None:
        body = json.dumps(response.body, allow_nan=False).encode()
        try:
            self.send_response(response.status)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
        except (OSError, TimeoutError):
            # The admission decision and model run are independent of delivery to the caller.
            pass

    def log_message(self, format, *args) -> None:
        pass


def main() -> None:
    token = os.environ["SIMULATION_SERVICE_TOKEN"]
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        raise ValueError("SIMULATION_SERVICE_TOKEN must contain 64 hexadecimal characters.")
    slots = int(os.environ["SIMULATION_SLOTS"])
    if slots < 1:
        raise ValueError("SIMULATION_SLOTS must be a positive integer.")
    bootstrap_path = os.environ.get("SIMULATION_BOOTSTRAP_MANIFEST")
    bootstrap = BootstrapCoverage.load(Path(bootstrap_path)) if bootstrap_path else None
    artifacts = Path(os.environ.get("MODEL_ARTIFACT_DIRECTORY", "/app/model-artifacts"))
    release_id = UUID(os.environ["MODEL_RELEASE_ID"])
    engine = create_engine(
        os.environ["SIMULATION_DATABASE_URL"],
        pool_size=2,
        max_overflow=0,
        pool_timeout=2,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 2, "options": "-c statement_timeout=3000"},
    )
    with Redis.from_url(
        os.environ["SIMULATION_REDIS_URL"],
        socket_connect_timeout=2,
        socket_timeout=2,
        retry=Retry(NoBackoff(), 0),
        max_connections=slots,
    ) as redis:
        service = Simulator(
            SimulationCatalog(engine, bootstrap),
            SimulationQuota(redis, bytes.fromhex(token)),
            (SeisModel(artifacts, release_id) for _ in range(slots)),
        )
        with SimulationServer(
            (os.environ.get("SIMULATION_HOST", "0.0.0.0"), 4350), service, token
        ) as server:
            server.serve_forever()


if __name__ == "__main__":
    main()
