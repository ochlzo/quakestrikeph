"""Explicit, audited reissue of SEIS 1.0 prediction work for SEIS 1.0.1."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update

from quakestrike.domain.features import INPUT_SCHEMA_VERSION, create_feature_snapshot
from quakestrike.infrastructure.database.engine import SessionFactory
from quakestrike.infrastructure.database.prediction import OUTPUT_SCHEMA_VERSION
from quakestrike.infrastructure.database.tables import (
    audit_logs,
    forecasts,
    job_dispatches,
    model_releases,
    prediction_attempts,
    prediction_jobs,
)

LEGACY_RELEASE_ID = UUID("2f532893-7a25-4f18-814c-91d66f38dac4")
TARGET_RELEASE_ID = UUID("a7f2286b-13a2-4708-a04d-4139281a4e1f")
REISSUE_REASON = "reissued_for_release"
REISSUE_ACTION = "prediction_backlog_reissued"
RECOVERABLE_FAILURES = frozenset({"unsupported_schema", "release_mismatch"})


class UnsafePredictionBacklog(ValueError):
    """The operator must resolve inconsistent or active work before reissue."""


class SqlAlchemyPredictionBacklogReissuer:
    def __init__(self, session_factory: SessionFactory, *, target_release_id: UUID) -> None:
        self._session_factory = session_factory
        self._target_release_id = target_release_id

    def run(self) -> dict[str, int]:
        """Move eligible work atomically; repeated calls leave completed reissues alone."""

        if self._target_release_id != TARGET_RELEASE_ID:
            raise UnsafePredictionBacklog("The selected release is not SEIS 1.0.1.")
        now = datetime.now(UTC)
        with self._session_factory() as session, session.begin():
            legacy = session.execute(
                select(model_releases).where(model_releases.c.model_release_id == LEGACY_RELEASE_ID)
            ).one_or_none()
            target = session.execute(
                select(model_releases).where(model_releases.c.model_release_id == TARGET_RELEASE_ID)
            ).one_or_none()
            if target is None or (target.input_schema_version, target.output_schema_version) != (
                INPUT_SCHEMA_VERSION,
                OUTPUT_SCHEMA_VERSION,
            ):
                raise UnsafePredictionBacklog("The selected release contract is unavailable.")
            if legacy is None:
                return {"reissued": 0, "reused": 0}
            if (legacy.input_schema_version, legacy.output_schema_version) != (
                INPUT_SCHEMA_VERSION,
                "quakestrike.prediction-output.v1",
            ):
                raise UnsafePredictionBacklog("The legacy release contract is unsupported.")

            old_ids = session.scalars(
                select(prediction_jobs.c.job_id)
                .where(
                    prediction_jobs.c.model_release_id == LEGACY_RELEASE_ID,
                    prediction_jobs.c.status.in_(("pending", "retry_wait", "running", "failed")),
                )
                .order_by(prediction_jobs.c.requested_at, prediction_jobs.c.job_id)
            ).all()
            reissued = reused = 0
            for old_id in old_ids:
                old_dispatch = session.execute(
                    select(job_dispatches)
                    .where(job_dispatches.c.prediction_job_id == old_id)
                    .with_for_update()
                ).one_or_none()
                old = session.execute(
                    select(prediction_jobs)
                    .where(prediction_jobs.c.job_id == old_id)
                    .with_for_update()
                ).one()
                if old.status == "running":
                    raise UnsafePredictionBacklog("A legacy prediction job is running.")
                if old.status == "failed" and old.last_error_code not in RECOVERABLE_FAILURES:
                    continue
                if old.status not in {"pending", "retry_wait", "failed"}:
                    continue
                if old_dispatch is None or old_dispatch.status == "dispatching":
                    raise UnsafePredictionBacklog("A legacy dispatch is missing or active.")
                if (
                    session.scalar(
                        select(prediction_attempts.c.attempt_id)
                        .where(
                            prediction_attempts.c.job_id == old_id,
                            prediction_attempts.c.status == "running",
                        )
                        .limit(1)
                    )
                    is not None
                ):
                    raise UnsafePredictionBacklog("A legacy prediction attempt is running.")
                if (
                    session.scalar(
                        select(forecasts.c.forecast_id).where(forecasts.c.job_id == old_id).limit(1)
                    )
                    is not None
                ):
                    raise UnsafePredictionBacklog("A legacy prediction already has a forecast.")
                snapshot = create_feature_snapshot(
                    old.input_snapshot_json, input_schema_version=legacy.input_schema_version
                )
                if snapshot.sha256 != old.input_snapshot_hash:
                    raise UnsafePredictionBacklog("A legacy prediction snapshot is invalid.")
                replacement = session.execute(
                    select(prediction_jobs)
                    .where(
                        prediction_jobs.c.event_revision_id == old.event_revision_id,
                        prediction_jobs.c.model_release_id == TARGET_RELEASE_ID,
                        prediction_jobs.c.input_snapshot_hash == snapshot.sha256,
                    )
                    .with_for_update()
                ).one_or_none()
                if replacement is None:
                    replacement_id = uuid4()
                    replacement_dispatch_id = uuid4()
                    session.execute(
                        insert(prediction_jobs).values(
                            job_id=replacement_id,
                            event_revision_id=old.event_revision_id,
                            model_release_id=TARGET_RELEASE_ID,
                            input_snapshot_hash=snapshot.sha256,
                            input_snapshot_json=dict(snapshot.values),
                            idempotency_key=(
                                f"prediction:{old.event_revision_id}:{TARGET_RELEASE_ID}:{snapshot.sha256}"
                            ),
                            status="pending",
                            requested_at=now,
                            correlation_id=old.correlation_id,
                        )
                    )
                    session.execute(
                        insert(job_dispatches).values(
                            dispatch_id=replacement_dispatch_id,
                            prediction_job_id=replacement_id,
                            status="pending",
                            next_dispatch_at=now,
                        )
                    )
                    reissued += 1
                else:
                    replacement_id = replacement.job_id
                    replacement_dispatch = session.execute(
                        select(job_dispatches).where(
                            job_dispatches.c.prediction_job_id == replacement_id
                        )
                    ).one_or_none()
                    if (
                        replacement.input_snapshot_json != dict(snapshot.values)
                        or replacement.correlation_id != old.correlation_id
                        or replacement_dispatch is None
                        or replacement.status in {"failed", "cancelled"}
                        or (
                            replacement.status == "succeeded"
                            and replacement_dispatch.status != "stopped"
                        )
                        or (
                            replacement.status in {"pending", "retry_wait", "running"}
                            and replacement_dispatch.status == "stopped"
                        )
                    ):
                        raise UnsafePredictionBacklog("Existing replacement work conflicts.")
                    replacement_dispatch_id = replacement_dispatch.dispatch_id
                    reused += 1
                session.execute(
                    update(prediction_jobs)
                    .where(prediction_jobs.c.job_id == old_id)
                    .values(
                        status="cancelled",
                        completed_at=now,
                        next_attempt_at=None,
                        last_error_code=REISSUE_REASON,
                        last_error_message="Reissued for SEIS 1.0.1 under a new prediction job.",
                    )
                )
                session.execute(
                    update(job_dispatches)
                    .where(job_dispatches.c.dispatch_id == old_dispatch.dispatch_id)
                    .values(
                        status="stopped",
                        next_dispatch_at=None,
                        lease_expires_at=None,
                        dispatch_token=None,
                        last_error=REISSUE_REASON,
                        updated_at=now,
                    )
                )
                session.execute(
                    insert(audit_logs).values(
                        audit_id=uuid4(),
                        actor_type="system",
                        actor_service="operator-cli",
                        action=REISSUE_ACTION,
                        target_type="prediction_job",
                        target_id=str(old_id),
                        outcome="succeeded",
                        reason_code=REISSUE_REASON,
                        correlation_id=old.correlation_id,
                        metadata={
                            "old_job_id": str(old_id),
                            "old_dispatch_id": str(old_dispatch.dispatch_id),
                            "old_release_id": str(LEGACY_RELEASE_ID),
                            "new_job_id": str(replacement_id),
                            "new_dispatch_id": str(replacement_dispatch_id),
                            "new_release_id": str(TARGET_RELEASE_ID),
                        },
                    )
                )
        return {"reissued": reissued, "reused": reused}
