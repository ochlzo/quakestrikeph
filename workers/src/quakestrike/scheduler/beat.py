"""Celery Beat entry point. Durable run creation arrives in a later phase."""

from __future__ import annotations

from quakestrike.runtime import run_service


def main() -> int:
    return run_service("scheduler-beat")


if __name__ == "__main__":
    raise SystemExit(main())
