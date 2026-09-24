"""Create the read-only database login without using a saved superuser password."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    ".env",
    "-f",
    "infrastructure/compose.yml",
]


def main() -> int:
    config = subprocess.run(
        [*COMPOSE, "config", "--environment"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if config.returncode:
        print("Could not read the Compose environment from .env.", file=sys.stderr)
        return config.returncode

    password = next(
        (
            line.partition("=")[2]
            for line in config.stdout.splitlines()
            if line.startswith("OBSERVER_DB_PASSWORD=")
        ),
        "",
    )
    if not password:
        print("Set OBSERVER_DB_PASSWORD in .env first.", file=sys.stderr)
        return 2

    command = (
        "IFS= read -r OBSERVER_DB_PASSWORD; "
        "export OBSERVER_DB_PASSWORD; "
        "sh /opt/quakestrike/provision-roles.sh create-observer"
    )
    result = subprocess.run(
        [*COMPOSE, "exec", "-T", "postgres", "sh", "-c", command],
        cwd=ROOT,
        input=(password + "\n").encode("utf-8"),
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
