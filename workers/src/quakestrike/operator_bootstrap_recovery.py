"""Reconstruct missing bootstrap evidence from a verified durable run."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, insert, select
from sqlalchemy.exc import SQLAlchemyError

from quakestrike.domain.features import select_usable_history
from quakestrike.infrastructure.bootstrap import (
    BootstrapSnapshotError,
    ensure_evidence_path_outside_git,
    evaluate_bootstrap_readiness,
    load_bootstrap_snapshot,
    load_enriched_snapshot,
    load_run_manifest,
    new_run_manifest,
)
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.database.feature_history import SqlAlchemyFeatureHistoryQuery
from quakestrike.infrastructure.database.migration_state import AlembicMigrationStateGate
from quakestrike.infrastructure.database.repositories import (
    SqlAlchemyIngestionTransactions,
    _ingestion_run_state,
)
from quakestrike.infrastructure.database.tables import audit_logs, ingestion_runs
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import (
    ConfiguredModelReleaseVerifier,
    ModelReleaseStartupGate,
)
from quakestrike.operator_output import print_json

_ACTION = "bootstrap_readiness_recovery_verified"
_RETENTION_LOCK = 5_173_835_459


def _publish_exclusively(path: Path, payload: bytes) -> None:
    """Publish a complete file without ever replacing existing evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".bootstrap-recovery-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
            factory = create_session_factory(engine)
            store = SqlAlchemyIngestionTransactions(
                factory, model_release_verifier=ConfiguredModelReleaseVerifier(settings)
            )
            with factory() as session, session.begin():
                # Share the same lock as checkpoint retention throughout verification.
                session.execute(select(func.pg_advisory_xact_lock(_RETENTION_LOCK)))
                statement = select(ingestion_runs).where(
                    ingestion_runs.c.trigger_type == "backfill",
                    ingestion_runs.c.status == "succeeded",
                )
                if run_id is not None:
                    statement = statement.where(ingestion_runs.c.run_id == run_id)
                rows = session.execute(statement.with_for_update()).mappings().all()
                if snapshot_path is not None:
                    source = load_bootstrap_snapshot(
                        snapshot_path,
                        required_available_through=settings.bootstrap_required_available_through,
                    )
                    candidates = [
                        row for row in rows if row["bootstrap_snapshot_sha256"] == source.sha256
                    ]
                else:
                    candidates = [
                        row
                        for row in rows
                        if (
                            target.parent
                            / "source-snapshots"
                            / f"{row['bootstrap_snapshot_sha256']}.source.json"
                        ).is_file()
                    ]
                if len(candidates) != 1:
                    raise BootstrapSnapshotError(
                        "Expected one completed run; specify --run-id and --snapshot if ambiguous."
                    )
                row = candidates[0]
                state = replace(
                    _ingestion_run_state(row),
                    retention_checked_at=session.scalar(select(func.now())),
                )
                if snapshot_path is None:
                    snapshot_path = (
                        target.parent / "source-snapshots" / f"{state.snapshot_sha256}.source.json"
                    )
                    source = load_bootstrap_snapshot(
                        snapshot_path,
                        required_available_through=settings.bootstrap_required_available_through,
                    )
                if source.sha256 != state.snapshot_sha256:
                    raise BootstrapSnapshotError(
                        "The source snapshot does not match the recorded hash."
                    )
                snapshot = source
                if state.enriched_snapshot_sha256 is not None:
                    if enriched_snapshot_path is None:
                        raise BootstrapSnapshotError("The bound enrichment cache is required.")
                    cache = enriched_snapshot_path.resolve()
                    if (
                        hashlib.sha256(cache.read_bytes()).hexdigest()
                        != state.enriched_snapshot_sha256
                    ):
                        raise BootstrapSnapshotError("The enrichment cache hash does not match.")
                    snapshot = load_enriched_snapshot(cache, source)
                elif source.snapshot_kind == "raw":
                    raise BootstrapSnapshotError("Raw evidence has no bound enrichment cache.")

                manifest = new_run_manifest(snapshot)
                manifest.update(
                    run_id=str(state.run_id),
                    correlation_id=str(state.correlation_id),
                    status=state.status,
                    attempt_count=state.attempt_count,
                    reconciliation_status="reconstructed",
                )
                manifest["counts"].update(
                    checkpointed_inputs=state.events_found,
                    events_inserted=state.events_inserted,
                    events_revised=state.events_revised,
                    events_unchanged=state.events_unchanged,
                    events_rejected=state.events_rejected,
                )
                if state.enriched_snapshot_sha256 is not None:
                    manifest["enriched_snapshot_path"] = str(enriched_snapshot_path.resolve())
                    manifest["enriched_snapshot_sha256"] = state.enriched_snapshot_sha256
                counts = store.bootstrap_database_counts(state.run_id)
                history = SqlAlchemyFeatureHistoryQuery(factory).select_history_at(
                    snapshot.coverage.first_prediction_anchor,
                    coverage=snapshot.coverage.history_coverage(),
                )
                usable = select_usable_history(
                    snapshot.coverage.first_prediction_anchor,
                    history.observations,
                    anchor_time_precision="minute",
                )
                readiness = evaluate_bootstrap_readiness(
                    snapshot,
                    manifest,
                    state,
                    history_observation_count=len(history.observations),
                    usable_history_count=len(usable),
                    database_counts=counts,
                )
                if not readiness.ready:
                    raise BootstrapSnapshotError(readiness.reason)
                audit_id = uuid5(
                    NAMESPACE_URL,
                    f"quakestrike-bootstrap-recovery:{state.run_id}:{source.sha256}:{target}",
                )
                manifest["recovery"] = {
                    "kind": "reconstructed",
                    "audit_id": str(audit_id),
                }
                payload = (
                    json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
                ).encode()
                digest = hashlib.sha256(payload).hexdigest()
                metadata = {
                    "snapshot_sha256": source.sha256,
                    "manifest_sha256": digest,
                    "manifest_path": str(target),
                    "checkpoint_count": counts["input_checkpoints"],
                    "event_revisions": counts["event_revisions"],
                    "usable_history_count": len(usable),
                }
                existing = (
                    session.execute(select(audit_logs).where(audit_logs.c.audit_id == audit_id))
                    .mappings()
                    .one_or_none()
                )
                if existing is not None and (
                    existing["action"] != _ACTION
                    or existing["target_id"] != str(state.run_id)
                    or existing["outcome"] != "succeeded"
                    or existing["metadata"] != metadata
                ):
                    raise BootstrapSnapshotError("The existing recovery audit record conflicts.")
                if target.exists():
                    saved = load_run_manifest(target)
                    saved.pop("readiness", None)
                    if saved != manifest:
                        if (
                            saved.get("run_id") == str(state.run_id)
                            and saved.get("correlation_id") == str(state.correlation_id)
                            and saved.get("snapshot_sha256") == source.sha256
                            and not saved.get("recovery")
                            and evaluate_bootstrap_readiness(
                                snapshot,
                                saved,
                                state,
                                history_observation_count=len(history.observations),
                                usable_history_count=len(usable),
                                database_counts=counts,
                            ).ready
                        ):
                            print_json(
                                {
                                    "action": "recover-bootstrap-readiness",
                                    "status": "existing_file_matches",
                                    "run_id": str(state.run_id),
                                }
                            )
                            return 0
                        raise BootstrapSnapshotError(
                            "The readiness file already exists and will not be replaced."
                        )
                    if existing is None:
                        raise BootstrapSnapshotError(
                            "The existing recovery file has no matching audit record."
                        )
                    print_json(
                        {
                            "action": "recover-bootstrap-readiness",
                            "status": "already_recovered",
                            "run_id": str(state.run_id),
                            "audit_id": str(audit_id),
                        }
                    )
                    return 0
                if not apply:
                    print_json(
                        {
                            "action": "recover-bootstrap-readiness",
                            "status": "ready_to_apply",
                            "run_id": str(state.run_id),
                            "snapshot_sha256": source.sha256,
                            "checkpoint_count": counts["input_checkpoints"],
                            "event_revisions": counts["event_revisions"],
                            "usable_history_count": len(usable),
                            "manifest_path": str(target),
                        }
                    )
                    return 0
                if existing is None:
                    session.execute(
                        insert(audit_logs).values(
                            audit_id=audit_id,
                            actor_type="system",
                            actor_service="operator-cli",
                            action=_ACTION,
                            target_type="ingestion_run",
                            target_id=str(state.run_id),
                            outcome="succeeded",
                            correlation_id=state.correlation_id,
                            metadata=metadata,
                        )
                    )
            # Commit the evidence audit before publishing. A retry resumes if publication fails.
            _publish_exclusively(target, payload)
            print_json(
                {
                    "action": "recover-bootstrap-readiness",
                    "status": "recovered",
                    "run_id": str(state.run_id),
                    "audit_id": str(audit_id),
                    "manifest_path": str(target),
                }
            )
            return 0
        finally:
            engine.dispose()
    except (BootstrapSnapshotError, OSError, SQLAlchemyError, ValueError) as error:
        print_json(
            {
                "action": "recover-bootstrap-readiness",
                "status": "rejected",
                "reason": str(error)
                if isinstance(error, BootstrapSnapshotError)
                else "Recovery could not verify or save evidence.",
            }
        )
        return 2
