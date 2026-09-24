"""Explicit migration and model-release setup commands."""

from __future__ import annotations

from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy.exc import SQLAlchemyError

from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
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
