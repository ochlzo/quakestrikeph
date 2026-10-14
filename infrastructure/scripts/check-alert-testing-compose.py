"""Check opt-in private packaging without target credentials or activation."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENT = {
    **os.environ,
    "ALERT_TEST_IMAGE_TAG": "0" * 40,
    "ALERT_TEST_REDIS_URL": "redis://alert-test-redis:6379/0",
    "ALERT_TEST_DATABASE_URL": "postgresql+psycopg://quakestrike_alert_testing:fixture@postgres:5432/quakestrike",
    "ALERT_TEST_ORIGIN": "https://quakestrike-vps.tailf8b2fd.ts.net:8443",
    "ALERT_TEST_PREPARATION_KEY": "fixture-only-preparation-key-at-least-32-bytes",
    "ALERT_TEST_PUBLIC_BULLETIN_URL": "https://bulletin.example.invalid",
    "ALERT_TEST_CONSUMER_ENABLED": "false",
    "ALERT_TEST_IPROG_TOKEN": "",
    "ALERT_TEST_BREVO_API_KEY": "",
}


def configuration(*files, profiles=()):
    command = ["docker", "compose", "--env-file", ".env.example"]
    for file in files:
        command.extend(["-f", f"infrastructure/{file}"])
    for profile in profiles:
        command.extend(["--profile", profile])
    command.extend(["config", "--format", "json"])
    return json.loads(
        subprocess.check_output(command, cwd=ROOT, env=ENVIRONMENT, text=True)
    )


def check():
    files = ("compose.yml", "compose.backend.yml", "compose.alert-testing.yml")
    disabled = configuration(*files)["services"]
    assert set(disabled) == {"postgres", "redis", "backend-api"}
    controls = configuration(*files, profiles=("alert-testing",))["services"]
    assert "alert-test-consumer" not in controls
    services = configuration(
        *files, profiles=("alert-testing", "alert-testing-consumer")
    )["services"]
    control, consumer = services["alert-test-control"], services["alert-test-consumer"]
    relay = services["alert-test-relay"]
    assert control["network_mode"] == "service:alert-test-relay"
    assert relay["ports"] == [
        {
            "mode": "ingress",
            "host_ip": "127.0.0.1",
            "target": 4342,
            "published": "4341",
            "protocol": "tcp",
        }
    ]
    assert not control.get("ports") and not consumer.get("ports")
    assert not services["alert-test-redis"].get("ports")
    assert not services["postgres"].get("ports")
    assert not services["redis"].get("ports")
    assert not services["alert-test-redis"].get("volumes")
    assert consumer["environment"]["ALERT_TEST_CONSUMER_ENABLED"] == "false"
    connection = ENVIRONMENT["ALERT_TEST_REDIS_URL"]
    assert all(
        services[name]["environment"]["ALERT_TEST_REDIS_URL"] == connection
        for name in ("backend-api", "alert-test-control", "alert-test-consumer")
    )
    assert not any("BREVO" in key or "IPROG" in key for key in control["environment"])
    for name in (
        "alert-test-control",
        "alert-test-consumer",
        "alert-test-relay",
        "alert-test-redis",
    ):
        service = services[name]
        assert (
            service["healthcheck"]
            and service["mem_limit"]
            and service["restart"] == "unless-stopped"
        )
        assert service["logging"]["driver"] == "local"
        assert not set(service.get("networks", {})) & {"backend-edge", "edge"}
    release = (ROOT / "infrastructure/scripts/deploy-workers.sh").read_text()
    assert "compose.alert-testing.yml" not in release
    print(
        "Private profiles, loopback relay, separate consumer, secrets, Redis selection, and release isolation passed."
    )


if __name__ == "__main__":
    check()
