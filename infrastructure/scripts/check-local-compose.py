"""Check local isolation and production edge composition without real secrets."""

import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]


def configuration(*files: str) -> dict:
    command = ["docker", "compose", "--env-file", ".env.example"]
    for file in files:
        command.extend(["-f", f"infrastructure/{file}"])
    command.extend(["config", "--format", "json"])
    return json.loads(subprocess.check_output(command, cwd=root, text=True))


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
}
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
for service in ("backend-api", "bulletin", "postgres", "redis"):
    assert not production["services"][service].get("ports")
print("Local isolation and explicit production edge checks passed.")
