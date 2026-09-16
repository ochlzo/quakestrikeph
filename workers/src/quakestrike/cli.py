"""Small operator-facing command entry point for the Phase 1 scaffold."""

from __future__ import annotations

import argparse

from quakestrike.runtime import run_service


def main() -> int:
    parser = argparse.ArgumentParser(prog="quakestrike")
    parser.add_argument(
        "command",
        choices=("config-check", "startup-check"),
        help="Run a read-only Phase 1 validation command.",
    )
    args = parser.parse_args()
    return run_service("cli", command=args.command)


if __name__ == "__main__":
    raise SystemExit(main())
