"""Durable dispatcher entry point. PostgreSQL dispatch claims arrive later."""

from __future__ import annotations

from quakestrike.runtime import run_service


def main() -> int:
    return run_service("scheduler-dispatcher")


if __name__ == "__main__":
    raise SystemExit(main())
