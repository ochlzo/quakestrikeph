from __future__ import annotations

from pathlib import Path


def test_worker_image_uses_an_exact_python_patch_image_and_digest() -> None:
    dockerfile = Path(__file__).parents[2] / "Dockerfile"
    first_line = dockerfile.read_text(encoding="utf-8").splitlines()[0]

    assert first_line.startswith("FROM python:3.12.14-slim-bookworm@sha256:")
    assert len(first_line.rsplit("@sha256:", maxsplit=1)[1]) == 64
