"""Small operator-facing command entry point for the Phase 1 scaffold."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.database.model_releases import SqlAlchemyModelReleaseRegistry
from quakestrike.infrastructure.models.packaging import package_selected_release
from quakestrike.infrastructure.models.release_manifest import (
    SELECTED_RELEASE_MANIFEST_URI,
    load_verified_release_manifest,
    model_release_record,
)
from quakestrike.infrastructure.settings import Settings
from quakestrike.runtime import run_service


def main() -> int:
    parser = argparse.ArgumentParser(prog="quakestrike")
    parser.add_argument(
        "command",
        choices=(
            "config-check",
            "startup-check",
            "package-model-release",
            "register-model-release",
        ),
    )
    parser.add_argument("--source-package", type=Path)
    args = parser.parse_args()
    if args.command == "package-model-release":
        if args.source_package is None:
            parser.error("package-model-release requires --source-package")
        try:
            settings = Settings()
            package_selected_release(args.source_package, settings.model_artifact_directory)
        except (OSError, ValueError):
            parser.error("model-release packaging failed")
        return 0
    if args.command == "register-model-release":
        try:
            settings = Settings()
            release = load_verified_release_manifest(
                settings.model_artifact_directory,
                SELECTED_RELEASE_MANIFEST_URI,
                require_selected_policy=True,
            )
            if release.release_id != settings.model_release_id:
                parser.error("MODEL_RELEASE_ID does not match the local release manifest")
            engine = create_database_engine(settings.database_url)
            try:
                SqlAlchemyModelReleaseRegistry(create_session_factory(engine)).register(
                    model_release_record(release)
                )
            finally:
                engine.dispose()
        except (OSError, SQLAlchemyError, ValueError):
            parser.error("model-release registration failed")
        return 0
    return run_service("cli", command=args.command)


if __name__ == "__main__":
    raise SystemExit(main())
