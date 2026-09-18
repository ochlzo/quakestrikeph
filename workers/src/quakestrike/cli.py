"""Small operator-facing command entry point for the Phase 1 scaffold."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from quakestrike.application.bootstrap import (
    BootstrapCommandResult,
    BootstrapEvidenceConflict,
)
from quakestrike.application.persistence import ActiveIngestionRun, RunIdentityConflict
from quakestrike.infrastructure.bootstrap import BootstrapSnapshotError
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
from quakestrike.infrastructure.startup import bootstrap_operation
from quakestrike.runtime import run_service


def main() -> int:
    parser = argparse.ArgumentParser(prog="quakestrike")
    parser.add_argument(
        "command",
        choices=(
            "config-check",
            "startup-check",
            "bootstrap",
            "bootstrap-recover",
            "bootstrap-readiness",
            "package-model-release",
            "register-model-release",
        ),
    )
    parser.add_argument("--source-package", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--run-manifest", type=Path)
    args = parser.parse_args()
    if args.command == "bootstrap":
        if args.snapshot is None:
            parser.error("bootstrap requires --snapshot")
        return _run_bootstrap(args.snapshot, args.run_manifest)
    if args.command == "bootstrap-recover":
        return _run_bootstrap_recover(args.run_manifest)
    if args.command == "bootstrap-readiness":
        return _run_bootstrap_readiness(args.run_manifest)
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


def _run_bootstrap(snapshot_path: Path, requested_manifest_path: Path | None) -> int:
    def execute() -> BootstrapCommandResult:
        settings = Settings()
        with bootstrap_operation(settings) as operation:
            return operation.execute(snapshot_path, requested_manifest_path)

    return _run_bootstrap_command(
        execute,
        unsafe_reason="bootstrap input or run state is unsafe",
        database_reason="bootstrap database work failed",
        failure_reason="bootstrap execution failed",
    )


def _run_bootstrap_recover(requested_manifest_path: Path | None) -> int:
    """Requeue a failed run without changing its durable identity."""

    def execute() -> BootstrapCommandResult:
        settings = Settings()
        with bootstrap_operation(settings) as operation:
            return operation.recover(requested_manifest_path)

    return _run_bootstrap_command(
        execute,
        unsafe_reason="bootstrap recovery is unsafe",
        database_reason="bootstrap recovery database work failed",
        failure_reason="bootstrap recovery failed",
    )


def _run_bootstrap_readiness(requested_manifest_path: Path | None) -> int:
    def execute() -> BootstrapCommandResult:
        settings = Settings()
        with bootstrap_operation(settings) as operation:
            return operation.readiness(requested_manifest_path)

    return _run_bootstrap_command(
        execute,
        unsafe_reason="bootstrap readiness evidence is invalid",
        database_reason="bootstrap readiness database work failed",
        failure_reason="bootstrap readiness check failed",
        unsafe_status="not_ready",
    )


def _run_bootstrap_command(
    execute: Callable[[], BootstrapCommandResult],
    *,
    unsafe_reason: str,
    database_reason: str,
    failure_reason: str,
    unsafe_status: str = "rejected",
) -> int:
    try:
        result = execute()
        _print_json(result.payload)
        return result.exit_code
    except (
        BootstrapSnapshotError,
        BootstrapEvidenceConflict,
        ActiveIngestionRun,
        RunIdentityConflict,
        ValidationError,
        ValueError,
    ):
        _print_json({"status": unsafe_status, "reason": unsafe_reason})
        return 2
    except SQLAlchemyError:
        _print_json({"status": "failed", "reason": database_reason})
        return 1
    except Exception:
        _print_json({"status": "failed", "reason": failure_reason})
        return 1


def _print_json(value: object) -> None:
    print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
