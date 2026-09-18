"""Small operator-facing command entry point for the Phase 1 scaffold."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from quakestrike import operator_runtime, operator_setup
from quakestrike.application.bootstrap import (
    BootstrapCommandResult,
    BootstrapEvidenceConflict,
)
from quakestrike.application.persistence import ActiveIngestionRun, RunIdentityConflict
from quakestrike.application.startup import evaluate_startup_gates
from quakestrike.infrastructure.bootstrap import (
    BootstrapSnapshotError,
    write_startup_readiness_manifest,
)
from quakestrike.infrastructure.logging.json_logging import (
    configure_logging,
    log_event,
    log_exception_event,
)
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import (
    bootstrap_operation,
    phase_one_startup_gates,
)
from quakestrike.operator_output import print_json as _print_json
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
            "verify-model-release",
            "poll-now",
            "migrate",
            "health-dispatcher",
            "health-ingestor",
            "health-beat",
        ),
    )
    parser.add_argument("--source-package", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--run-manifest", type=Path)
    args = parser.parse_args()
    if args.command == "migrate":
        return operator_setup.migrate()
    if args.command == "bootstrap":
        if args.snapshot is None:
            parser.error("bootstrap requires --snapshot")
        return _run_bootstrap(args.snapshot, args.run_manifest)
    if args.command == "bootstrap-recover":
        return _run_bootstrap_recover(args.run_manifest)
    if args.command == "startup-check":
        return _run_startup_check(args.run_manifest)
    if args.command == "bootstrap-readiness":
        return _run_bootstrap_readiness(args.run_manifest)
    if args.command == "package-model-release":
        if args.source_package is None:
            parser.error("package-model-release requires --source-package")
        return operator_setup.package_model_release(args.source_package)
    if args.command == "register-model-release":
        return operator_setup.register_model_release()
    if args.command == "verify-model-release":
        return operator_setup.verify_model_release()
    if args.command == "poll-now":
        return operator_runtime.immediate_poll()
    if args.command in {"health-dispatcher", "health-ingestor", "health-beat"}:
        return operator_runtime.worker_health(args.command)
    return run_service("cli", command=args.command)


def _run_startup_check(requested_manifest_path: Path | None) -> int:
    """Evaluate all read-only gates and persist the operator proof."""

    try:
        settings = Settings()
        manifest_path = (requested_manifest_path or settings.bootstrap_run_manifest).resolve()
        if requested_manifest_path is not None:
            settings = settings.model_copy(update={"bootstrap_run_manifest": manifest_path})
        logger = configure_logging("startup-check", level=settings.log_level, stream=sys.stderr)
        report = evaluate_startup_gates(phase_one_startup_gates(settings))
        for result in report.results:
            log_event(
                logger,
                logging.INFO if result.ready else logging.WARNING,
                "startup gate evaluated",
                event_code="startup_gate_result",
                context={
                    "gate": result.name,
                    "reason": result.reason,
                    "status": "ready" if result.ready else "not_ready",
                },
            )
        if not report.ready:
            log_event(
                logger,
                logging.ERROR,
                "startup readiness failed",
                event_code="startup_not_ready",
                context={"reason": ", ".join(report.failed_gate_names)},
            )
        try:
            write_startup_readiness_manifest(
                manifest_path,
                report,
                checked_at=datetime.now(UTC),
            )
        except BootstrapSnapshotError:
            log_event(
                logger,
                logging.ERROR,
                "readiness manifest could not be updated",
                event_code="readiness_manifest_invalid",
                context={"reason": "existing bootstrap evidence is invalid"},
            )
            output = report.as_dict()
            output["ready"] = False
            output["failed_gate_names"] = [
                *report.failed_gate_names,
                "readiness-manifest",
            ]
            output["manifest_path"] = str(manifest_path)
            _print_json(output)
            return 2
        output = report.as_dict()
        output["manifest_path"] = str(manifest_path)
        _print_json(output)
        return 0 if report.ready else 2
    except ValidationError as error:
        logger = configure_logging("startup-check", stream=sys.stderr)
        log_exception_event(
            logger,
            logging.ERROR,
            "startup check configuration is invalid",
            event_code="configuration_invalid",
            error=error,
        )
        _print_json(
            {
                "ready": False,
                "failed_gate_names": ["configuration"],
                "results": [],
            }
        )
        return 2
    except Exception as error:
        logger = configure_logging("startup-check", stream=sys.stderr)
        log_exception_event(
            logger,
            logging.ERROR,
            "startup check failed",
            event_code="startup_check_failed",
            error=error,
        )
        _print_json({"status": "failed", "reason": "startup check failed"})
        return 1


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


if __name__ == "__main__":
    raise SystemExit(main())
