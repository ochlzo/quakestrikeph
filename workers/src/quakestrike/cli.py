"""Small operator-facing command entry point for the Phase 1 scaffold."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from quakestrike.application.bootstrap import run_bootstrap
from quakestrike.application.persistence import ActiveIngestionRun, RunIdentityConflict
from quakestrike.application.phivolcs import CatalogRetrievalLeaseLost
from quakestrike.application.reconciliation import ReconcileSourceRows
from quakestrike.application.startup import evaluate_startup_gates
from quakestrike.infrastructure.bootstrap import (
    BootstrapSnapshotError,
    default_run_manifest_path,
    evaluate_bootstrap_readiness,
    load_bootstrap_snapshot,
    load_run_manifest,
    prepare_run_manifest,
    write_run_manifest,
    write_startup_readiness_manifest,
)
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.database.model_releases import SqlAlchemyModelReleaseRegistry
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.logging.json_logging import (
    configure_logging,
    log_event,
    log_exception_event,
)
from quakestrike.infrastructure.logging.reconciliation import (
    StructuredReconciliationDiagnosticReporter,
)
from quakestrike.infrastructure.models.packaging import package_selected_release
from quakestrike.infrastructure.models.release_manifest import (
    SELECTED_RELEASE_MANIFEST_URI,
    load_verified_release_manifest,
    model_release_record,
)
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import (
    ConfiguredModelReleaseVerifier,
    phase_one_startup_gates,
)
from quakestrike.runtime import run_service


def main() -> int:
    parser = argparse.ArgumentParser(prog="quakestrike")
    parser.add_argument(
        "command",
        choices=(
            "config-check",
            "startup-check",
            "bootstrap",
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
    if args.command == "startup-check":
        return _run_startup_check(args.run_manifest)
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
        write_startup_readiness_manifest(
            manifest_path,
            report,
            checked_at=datetime.now(UTC),
        )
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
    engine = None
    try:
        settings = Settings()
        snapshot = load_bootstrap_snapshot(snapshot_path)
        manifest_path = (
            requested_manifest_path or default_run_manifest_path(snapshot.path)
        ).resolve()
        manifest_exists = manifest_path.exists()
        engine = create_database_engine(settings.database_url)
        store = SqlAlchemyIngestionTransactions(
            create_session_factory(engine),
            model_release_verifier=ConfiguredModelReleaseVerifier(settings),
        )
        if not manifest_exists and store.backfill_run_exists():
            raise BootstrapSnapshotError(
                "The run manifest is missing while a durable backfill run already exists."
            )
        manifest = prepare_run_manifest(snapshot, manifest_path)
        logger = configure_logging("bootstrap", level=settings.log_level, stream=sys.stderr)

        def snapshot_loader(*, heartbeat=None):
            if heartbeat is not None and not heartbeat():
                raise CatalogRetrievalLeaseLost()
            return snapshot.parsed

        reconciler = ReconcileSourceRows(
            store=store,
            source_loader=snapshot_loader,
            diagnostic_reporter=StructuredReconciliationDiagnosticReporter(logger),
            model_release_id=settings.model_release_id,
            history_coverage=snapshot.coverage.history_coverage(),
        )
        result = run_bootstrap(
            store=store,
            reconciler=reconciler,
            run_id=_manifest_uuid(manifest, "run_id"),
            correlation_id=_manifest_uuid(manifest, "correlation_id"),
            manifest=manifest,
            write_manifest=lambda current: write_run_manifest(manifest_path, current),
        )
        readiness = evaluate_bootstrap_readiness(snapshot, manifest, result.state)
        _print_json(
            {
                "bootstrap": result.as_dict(),
                "readiness": readiness.as_dict(),
                "snapshot_sha256": snapshot.sha256,
            }
        )
        return 0 if result.state.status == "succeeded" else 2
    except (BootstrapSnapshotError, ActiveIngestionRun, RunIdentityConflict, ValidationError):
        _print_json({"status": "rejected", "reason": "bootstrap input or run state is unsafe"})
        return 2
    except SQLAlchemyError:
        _print_json({"status": "failed", "reason": "bootstrap database work failed"})
        return 1
    except Exception:
        _print_json({"status": "failed", "reason": "bootstrap execution failed"})
        return 1
    finally:
        if engine is not None:
            engine.dispose()


def _run_bootstrap_readiness(requested_manifest_path: Path | None) -> int:
    engine = None
    try:
        settings = Settings()
        manifest_path = (requested_manifest_path or settings.bootstrap_run_manifest).resolve()
        manifest = load_run_manifest(manifest_path)
        snapshot = load_bootstrap_snapshot(Path(str(manifest["snapshot_path"])))
        engine = create_database_engine(settings.database_url)
        store = SqlAlchemyIngestionTransactions(
            create_session_factory(engine),
            model_release_verifier=ConfiguredModelReleaseVerifier(settings),
        )
        state = store.get_ingestion_run(_manifest_uuid(manifest, "run_id"))
        readiness = evaluate_bootstrap_readiness(snapshot, manifest, state)
        _print_json(
            {
                "readiness": readiness.as_dict(),
                "snapshot_sha256": snapshot.sha256,
                "run_id": manifest.get("run_id"),
            }
        )
        return 0 if readiness.ready else 2
    except (BootstrapSnapshotError, ValidationError):
        _print_json({"status": "not_ready", "reason": "bootstrap readiness evidence is invalid"})
        return 2
    except SQLAlchemyError:
        _print_json({"status": "failed", "reason": "bootstrap readiness database work failed"})
        return 1
    except Exception:
        _print_json({"status": "failed", "reason": "bootstrap readiness check failed"})
        return 1
    finally:
        if engine is not None:
            engine.dispose()


def _manifest_uuid(manifest: dict[str, object], key: str) -> UUID:
    return UUID(str(manifest[key]))


def _print_json(value: object) -> None:
    print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
