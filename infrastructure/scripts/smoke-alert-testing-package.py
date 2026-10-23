"""Probe packaged controls with disposable Redis and no provider credentials."""

import json
import os
import re
import runpy
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
SERVICES = [
    "alert-test-redis",
    "alert-test-relay",
    "alert-test-control",
    "alert-test-consumer",
]
ORIGIN = "https://quakestrike-vps.tailf8b2fd.ts.net:8443"
AUTHORITY = "quakestrike-vps.tailf8b2fd.ts.net:8443"


def request(path, body=None, *, host=AUTHORITY, origin=ORIGIN):
    headers = {"Host": host}
    if body is not None:
        headers.update(
            {
                "Origin": origin,
                "Content-Type": "application/json",
                "X-QuakeStrike-Test": "1",
            }
        )
    query = Request(
        "http://127.0.0.1:4341" + path,
        headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        response = urlopen(query, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read()


def main(tag):
    with socket.socket() as port:
        port.settimeout(1)
        if port.connect_ex(("127.0.0.1", 4341)) == 0:
            raise SystemExit(
                "Port 4341 is occupied. Stop the separate preview before this check."
            )
    checker = runpy.run_path(
        str(ROOT / "infrastructure/scripts/check-alert-testing-compose.py")
    )
    configuration = checker["configuration"](
        "compose.yml",
        "compose.alert-testing.yml",
        profiles=("alert-testing", "alert-testing-consumer"),
    )
    services = {name: configuration["services"][name] for name in SERVICES}
    for service in services.values():
        service.pop("profiles", None)
        service.pop("build", None)
        if service["image"].startswith("quakestrike-"):
            service["image"] = service["image"].split(":")[0] + ":" + tag
        if "environment" in service:
            service["environment"].update(
                ALERT_TEST_DATABASE_URL="postgresql+psycopg://quakestrike_alert_testing:integration-only@postgres-test:5432/quakestrike_test"
            )
        dependencies = service.get("depends_on", {})
        if "postgres" in dependencies:
            dependencies["postgres-test"] = dependencies.pop("postgres")
    services["alert-test-consumer"]["environment"]["ALERT_TEST_CONSUMER_ENABLED"] = (
        "true"
    )
    # Recovery checks own their disposable resources explicitly for scoped cleanup.
    owner = os.environ.get("QUAKESTRIKE_TRANSFER_OWNER")
    labels = {"io.quakestrike.transfer": owner} if owner else {}
    if owner:
        for service in services.values():
            service["labels"] = labels
        services["postgres-test"] = {"labels": labels}
        services["redis-test"] = {"labels": labels}
    with tempfile.TemporaryDirectory(prefix="quakestrike-package-test-") as directory:
        overlay = Path(directory) / "compose.json"
        overlay.write_text(
            json.dumps(
                {
                    "services": services,
                    "networks": {
                        "private-data": {
                            "external": True,
                            "name": "quakestrike-data-ingestion-test_phase2-test",
                        },
                        "alert-test-access": {"labels": labels},
                        "alert-test-egress": {"internal": True, "labels": labels},
                        "phase2-test": {"labels": labels},
                    },
                }
            )
        )
        compose = [
            "docker",
            "compose",
            "-p",
            "quakestrike-data-ingestion-test",
            "-f",
            str(ROOT / "infrastructure/compose.integration.yml"),
            "-f",
            str(overlay),
        ]

        def run(*args):
            subprocess.run([*compose, *args], cwd=ROOT, check=True)

        try:
            run("up", "-d", "--wait", *SERVICES)
            assert request("/api/test/session", host="127.0.0.1:4341")[0] == 403
            assert (
                request(
                    "/api/test/session",
                    host=ORIGIN.removeprefix("https://").replace(":8443", ""),
                )[0]
                == 403
            )
            assert (
                request(
                    "/api/test/session/start", {}, origin=ORIGIN.replace(":8443", "")
                )[0]
                == 403
            )
            for page in (
                "/",
                "/testers",
                "/history",
                "/results/00000000-0000-4000-8000-000000000001",
            ):
                status, html = request(page)
                assert status == 200 and b"/_astro/" in html
            asset = re.search(rb'(?:src|href)="(/_astro/[^\"]+)"', request("/")[1])
            assert asset and request(asset[1].decode())[0] == 200
            status, places = request("/assets/accounts/philippine-places.json")
            assert status == 200 and len(json.loads(places)) > 0
            status, session = request("/api/test/session/start", {})
            assert status == 200
            owner = json.loads(session)["session_id"]
            assert request("/api/test/session/end", {"session_id": owner})[0] == 200
            print(
                "Packaged pages/assets, exact Host/Origin, session Start/End, relay and consumer health passed; no sends."
            )
        except Exception:
            subprocess.run(
                [*compose, "logs", "--tail", "20", "alert-test-relay"],
                cwd=ROOT,
                check=False,
            )
            subprocess.run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "alert-test-relay",
                    "traefik",
                    "healthcheck",
                    "--ping",
                    "--ping.entrypoint=health",
                    "--entrypoints.health.address=127.0.0.1:8082",
                ],
                cwd=ROOT,
                check=False,
            )
            raise
        finally:
            run(
                "stop",
                "alert-test-control",
                "alert-test-consumer",
                "alert-test-relay",
                "alert-test-redis",
            )
            run("rm", "-f", "-v", *SERVICES)
            subprocess.run(
                [
                    "docker",
                    "network",
                    "rm",
                    "quakestrike-data-ingestion-test_alert-test-access",
                    "quakestrike-data-ingestion-test_alert-test-egress",
                ],
                cwd=ROOT,
                check=True,
            )


if __name__ == "__main__":
    main(sys.argv[1])
