"""Data Ingestor entry point. Source retrieval arrives in a later phase."""

from __future__ import annotations

from quakestrike.runtime import run_service


def main() -> int:
    return run_service("data-ingestor")


if __name__ == "__main__":
    raise SystemExit(main())
