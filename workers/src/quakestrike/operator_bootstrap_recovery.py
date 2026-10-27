"""Compose the bootstrap recovery use case and report its operator result."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from quakestrike.application.bootstrap_recovery import (
    RecoverBootstrapReadiness,
    UnsafeBootstrapRecovery,
)
from quakestrike.infrastructure.bootstrap import (
    BootstrapSnapshotError,
    ensure_evidence_path_outside_git,
)
from quakestrike.infrastructure.bootstrap_recovery import FileBootstrapRecoveryEvidence
from quakestrike.infrastructure.database.bootstrap_recovery import SqlAlchemyBootstrapRecovery
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.database.migration_state import AlembicMigrationStateGate
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import ModelReleaseStartupGate
from quakestrike.operator_output import print_json


def recover_bootstrap_readiness(
    *,
    apply: bool,
    snapshot_path: Path | None,
    enriched_snapshot_path: Path | None,
    manifest_path: Path | None,
    run_id: UUID | None,
) -> int:
    """Check evidence, then optionally record and publish a reconstructed sidecar."""
    try:
        settings = Settings()
        target = (manifest_path or settings.bootstrap_run_manifest).resolve()
        ensure_evidence_path_outside_git(target)
        if not AlembicMigrationStateGate(settings).check().ready:
            raise BootstrapSnapshotError("Database migrations are not ready.")
        if not ModelReleaseStartupGate(settings).check().ready:
            raise BootstrapSnapshotError("The selected model release is not ready.")
        engine = create_database_engine(settings.database_url)
        try:
            operation = RecoverBootstrapReadiness(
                SqlAlchemyBootstrapRecovery(create_session_factory(engine)),
                FileBootstrapRecoveryEvidence(
                    required_available_through=settings.bootstrap_required_available_through
                ),
            )
            result = operation.run(
                apply=apply,
                snapshot_path=snapshot_path,
                enriched_snapshot_path=enriched_snapshot_path,
                manifest_path=target,
                run_id=run_id,
            )
        finally:
            engine.dispose()
        print_json(result)
        return 0
    except (
        UnsafeBootstrapRecovery,
        BootstrapSnapshotError,
        OSError,
        SQLAlchemyError,
        ValueError,
    ) as error:
        print_json(
            {
                "action": "recover-bootstrap-readiness",
                "status": "rejected",
                "reason": str(error)
                if isinstance(error, (UnsafeBootstrapRecovery, BootstrapSnapshotError))
                else "Recovery could not verify or save evidence.",
            }
        )
        return 2
