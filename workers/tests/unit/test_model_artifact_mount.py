from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_future_worker_artifact_mount_is_explicit_and_read_only() -> None:
    compose = (Path(__file__).resolve().parents[3] / "infrastructure" / "compose.yml").read_text(
        encoding="utf-8"
    )

    assert "x-future-worker-artifact-mount:" in compose
    assert ":/app/model-artifacts:ro" in compose
    assert "model-artifacts" in (Path(__file__).resolve().parents[3] / ".dockerignore").read_text(
        encoding="utf-8"
    )


def test_rendered_future_mount_is_a_read_only_host_bind(tmp_path: Path) -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is unavailable")
    root = Path(__file__).resolve().parents[3]
    base = root / "infrastructure" / "compose.yml"
    env = root / ".env.example"
    rendered = json.loads(
        subprocess.check_output(
            [
                "docker",
                "compose",
                "--env-file",
                str(env),
                "-f",
                str(base),
                "config",
                "--format",
                "json",
            ],
            text=True,
        )
    )
    mount = rendered["x-future-worker-artifact-mount"][0]
    override = tmp_path / "mount.yml"
    override.write_text(
        "services:\n  mount-check:\n    image: busybox\n    volumes:\n      - "
        + json.dumps(mount)
        + "\n",
        encoding="utf-8",
    )
    combined = json.loads(
        subprocess.check_output(
            [
                "docker",
                "compose",
                "--env-file",
                str(env),
                "-f",
                str(base),
                "-f",
                str(override),
                "config",
                "--format",
                "json",
            ],
            text=True,
        )
    )
    volume = combined["services"]["mount-check"]["volumes"][0]
    assert volume["type"] == "bind"
    assert Path(volume["source"]).resolve() == (root / "workers" / "model-artifacts").resolve()
    assert volume["target"] == "/app/model-artifacts"
    assert volume["read_only"] is True
