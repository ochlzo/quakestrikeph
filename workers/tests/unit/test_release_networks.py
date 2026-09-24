from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_only_ingestor_has_public_egress_in_release_compose() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is unavailable")

    root = Path(__file__).resolve().parents[3]
    rendered = json.loads(
        subprocess.check_output(
            [
                "docker",
                "compose",
                "--env-file",
                str(root / ".env.example"),
                "-f",
                str(root / "infrastructure" / "compose.yml"),
                "-f",
                str(root / "infrastructure" / "compose.release.yml"),
                "--profile",
                "init",
                "--profile",
                "prediction",
                "--profile",
                "beat",
                "config",
                "--format",
                "json",
            ],
            env={**os.environ, "WORKER_IMAGE_TAG": "0" * 40},
            text=True,
        )
    )
    services = rendered["services"]
    networks = rendered["networks"]

    assert networks["private-data"]["internal"] is True
    assert networks["source-egress"].get("internal", False) is False
    assert set(services["data-ingestor"]["networks"]) == {"private-data", "source-egress"}
    for name in ("postgres", "redis", "dispatcher", "prediction-worker", "beat", "release-init"):
        assert set(services[name]["networks"]) == {"private-data"}
