"""Explicit migration and model-release setup commands."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy.exc import SQLAlchemyError

from quakestrike.infrastructure.bootstrap import (
    BootstrapSnapshotError,
    load_run_manifest,
    load_snapshot_for_manifest,
)
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.database.historical_recovery import (
    SqlAlchemyHistoricalRecovery,
    UnsafeHistoricalRecovery,
)
from quakestrike.infrastructure.database.migration_state import AlembicMigrationStateGate
from quakestrike.infrastructure.database.model_releases import SqlAlchemyModelReleaseRegistry
from quakestrike.infrastructure.database.prediction_backlog import (
    SqlAlchemyPredictionBacklogReissuer,
    UnsafePredictionBacklog,
)
from quakestrike.infrastructure.models.packaging import package_selected_release
from quakestrike.infrastructure.models.release_manifest import (
    SELECTED_RELEASE_MANIFEST_URI,
    load_verified_release_manifest,
    model_release_record,
)
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import ModelReleaseStartupGate
from quakestrike.operator_output import print_json


def migrate() -> int:
    try:
        settings = Settings()
        alembic_command.upgrade(AlembicConfig("alembic.ini"), "head")
        result = AlembicMigrationStateGate(settings).check()
        print_json(
            {
                "action": "migrate",
                "status": "applied" if result.ready else "not_ready",
                "reason": result.reason,
                "details": dict(result.details),
            }
        )
        return 0 if result.ready else 2
    except Exception:
        print_json({"action": "migrate", "status": "failed", "reason": "migration failed safely"})
        return 2


def package_model_release(source_package: Path) -> int:
    try:
        settings = Settings()
        package_selected_release(source_package, settings.model_artifact_directory)
    except (OSError, ValueError):
        print_json({"action": "package-model-release", "status": "failed"})
        return 2
    print_json({"action": "package-model-release", "status": "packaged"})
    return 0


def register_model_release() -> int:
    try:
        settings = Settings()
        release = load_verified_release_manifest(
            settings.model_artifact_directory,
            SELECTED_RELEASE_MANIFEST_URI,
            require_selected_policy=True,
        )
        if release.release_id != settings.model_release_id:
            print_json({"action": "register-model-release", "status": "not_ready"})
            return 2
        engine = create_database_engine(settings.database_url)
        try:
            SqlAlchemyModelReleaseRegistry(create_session_factory(engine)).register(
                model_release_record(release)
            )
        finally:
            engine.dispose()
    except (OSError, SQLAlchemyError, ValueError):
        print_json({"action": "register-model-release", "status": "failed"})
        return 2
    print_json(
        {
            "action": "register-model-release",
            "status": "registered",
            "release_id": str(release.release_id),
            "manifest_hash": release.manifest_hash,
        }
    )
    return 0


def verify_model_release() -> int:
    try:
        result = ModelReleaseStartupGate(Settings()).check()
        print_json(
            {
                "action": "verify-model-release",
                "status": "verified" if result.ready else "not_ready",
                "reason": result.reason,
                "details": dict(result.details),
            }
        )
        return 0 if result.ready else 2
    except Exception:
        print_json(
            {
                "action": "verify-model-release",
                "status": "failed",
                "reason": "verification could not run",
            }
        )
        return 2


def reissue_legacy_predictions() -> int:
    """Run the reviewed SEIS 1.0 backlog transition before worker startup."""

    try:
        settings = Settings()
        migration = AlembicMigrationStateGate(settings).check()
        release = ModelReleaseStartupGate(settings).check()
        if not migration.ready or not release.ready:
            print_json(
                {
                    "action": "reissue-legacy-predictions",
                    "status": "not_ready",
                    "reason": "Migration or selected model release verification failed.",
                }
            )
            return 2
        engine = create_database_engine(settings.database_url)
        try:
            counts = SqlAlchemyPredictionBacklogReissuer(
                create_session_factory(engine), target_release_id=settings.model_release_id
            ).run()
        finally:
            engine.dispose()
    except (UnsafePredictionBacklog, SQLAlchemyError, ValueError):
        print_json(
            {
                "action": "reissue-legacy-predictions",
                "status": "rejected",
                "reason": "Legacy work is active or inconsistent; no jobs were reissued.",
            }
        )
        return 2
    print_json({"action": "reissue-legacy-predictions", "status": "completed", **counts})
    return 0


def recover_historical_predictions(*, apply: bool, batch_size: int = 50) -> int:
    """Preview or create audited prediction work for the one affected live run."""

    action = "recover-historical-predictions"
    try:
        settings = Settings()
        if not AlembicMigrationStateGate(settings).check().ready:
            raise UnsafeHistoricalRecovery("Migrations are not ready.")
        if not ModelReleaseStartupGate(settings).check().ready:
            raise UnsafeHistoricalRecovery("The selected model release is not ready.")
        manifest = load_run_manifest(settings.bootstrap_run_manifest)
        snapshot = load_snapshot_for_manifest(manifest)
        if manifest["status"] != "succeeded" or snapshot.sha256 != manifest["snapshot_sha256"]:
            raise UnsafeHistoricalRecovery(
                "The bootstrap source snapshot does not match its manifest."
            )
        engine = create_database_engine(settings.database_url)
        try:
            counts = SqlAlchemyHistoricalRecovery(
                create_session_factory(engine),
                target_release_id=settings.model_release_id,
                bootstrap_run_id=UUID(manifest["run_id"]),
                bootstrap_sha256=snapshot.sha256,
                bootstrap_coverage=snapshot.coverage.history_coverage(),
            ).run(
                apply=apply,
                max_new_jobs=batch_size,
                progress=(
                    (lambda counts: print_json({"action": action, "status": "progress", **counts}))
                    if apply
                    else None
                ),
            )
        finally:
            engine.dispose()
    except (BootstrapSnapshotError, UnsafeHistoricalRecovery, SQLAlchemyError, ValueError):
        print_json(
            {
                "action": action,
                "status": "rejected",
                "reason": "Recovery evidence or work is inconsistent.",
            }
        )
        return 2
    print_json({"action": action, "status": "completed" if apply else "dry_run", **counts})
    return 0
