"""Check local isolation and production edge composition without real secrets."""

import json
import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]


def configuration(*files: str, profiles=()) -> dict:
    command = ["docker", "compose", "--env-file", ".env.example"]
    for file in files:
        command.extend(["-f", f"infrastructure/{file}"])
    for profile in profiles:
        command.extend(["--profile", profile])
    command.extend(["config", "--format", "json"])
    environment = {
        **os.environ,
        "WORKER_IMAGE_TAG": "0" * 40,
        "CONTROLLED_DATABASE_URL": "postgresql+psycopg://quakestrike_worker:fixture@postgres-test:5432/quakestrike_test",
        "LOCAL_ACCOUNT_API_TARGET": "http://backend-api:3000",
        "LOCAL_API_TARGET": "http://backend-api:3000",
    }
    return json.loads(
        subprocess.check_output(command, cwd=root, text=True, env=environment)
    )


base = configuration("compose.yml")
local = configuration("compose.yml", "compose.backend.yml", "compose.local.yml")
services = local["services"]
assert local["name"] == base["name"] == "infrastructure"
assert set(services) == {"postgres", "redis", "backend-api", "bulletin"}
for service in ("postgres", "redis"):
    assert not services[service].get("ports")
    assert services[service]["volumes"] == base["services"][service]["volumes"]
for service in ("backend-api", "bulletin"):
    assert all(port["host_ip"] == "127.0.0.1" for port in services[service]["ports"])
assert set(services["bulletin"]["environment"]) == {
    "PUBLIC_CLERK_PUBLISHABLE_KEY",
    "ACCOUNT_API_TARGET",
    "API_TARGET",
    "DEV_USE_POLLING",
    "CI",
}
assert services["bulletin"]["environment"]["DEV_USE_POLLING"] == "true"
assert services["bulletin"]["environment"]["CI"] == "true"
assert services["bulletin"]["environment"]["API_TARGET"] == "http://backend-api:3000"
assert (
    services["bulletin"]["environment"]["ACCOUNT_API_TARGET"]
    == "http://backend-api:3000"
)
assert "redis" in services["backend-api"]["depends_on"]
production = configuration(
    "compose.yml", "compose.backend.yml", "compose.edge.yml", "compose.bulletin.yml"
)
assert {"traefik", "cloudflared"} <= set(production["services"])
bulletin = production["services"]["bulletin"]
assert set(bulletin["build"]["args"]) == {"PUBLIC_CLERK_PUBLISHABLE_KEY"}
assert (
    bulletin["build"]["labels"]["org.opencontainers.image.revision"]
    == bulletin["image"].rsplit(":", 1)[1]
)
for service in ("backend-api", "bulletin", "postgres", "redis"):
    assert not production["services"][service].get("ports")
release = configuration("compose.yml", "compose.release.yml")
assert "alert-worker" not in release["services"]
assert "alert-reconciliation" not in release["services"]
alerts = configuration(
    "compose.yml", "compose.release.yml", profiles=("alerts", "prediction")
)
services = alerts["services"]
assert services["dispatcher"]["environment"]["ALERT_RESOLUTION_ENABLED"] == "false"
assert services["alert-worker"]["environment"]["ALERT_DELIVERY_ENABLED"] == "false"
assert "BREVO_API_KEY" in services["alert-worker"]["environment"]
assert "BREVO_API_KEY" not in services["alert-reconciliation"]["environment"]
assert "BREVO_CALLBACK_TOKEN" not in services["alert-worker"]["environment"]
assert "BREVO_CALLBACK_TOKEN" in local["services"]["backend-api"]["environment"]
for service in ("dispatcher", "prediction-worker", "beat"):
    if service in services:
        assert not {"IPROG_API_TOKEN", "BREVO_API_KEY", "BREVO_CALLBACK_TOKEN"} & set(
            services[service]["environment"]
        )
assert services["prediction-worker"]["environment"]["PUBLIC_BULLETIN_BASE_URL"] == (
    "https://quakestrikeph.qzz.io"
)
controlled = configuration(
    "compose.integration.yml",
    "compose.alert-verification.yml",
    profiles=("controlled-alert",),
)
fixture = controlled["services"]["controlled-alert"]
assert set(fixture["networks"]) == {"phase2-test"}
assert fixture["restart"] == "no"
assert not {"beat", "dispatcher", "alert-worker", "alert-reconciliation"} & set(
    controlled["services"]
)
assert "BREVO_CALLBACK_TOKEN" not in fixture["environment"]
print(
    "Local isolation, explicit edge, disabled alerts, and finite fixture checks passed."
)
