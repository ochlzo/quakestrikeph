"""Policy and orchestration for recovering the one skipped live catalog run."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from quakestrike.application.features import PredictionSnapshotRequest, decide_prediction_snapshot
from quakestrike.application.reconciliation import coverage_for_anchor, merge_history_coverages
from quakestrike.domain.features import (
    INPUT_SCHEMA_VERSION,
    FeatureObservation,
    FeatureSnapshot,
    HistoryCoverage,
    evaluate_history_readiness,
)

SOURCE_RUN_ID = UUID("adc80d19-d105-4ef7-b427-6bc52f133b4d")
AUDIT_ACTION = "historical_prediction_recovered"
SKIP_REASON = "history_coverage_unavailable"
OUTPUT_SCHEMA_VERSION = "quakestrike.prediction-output.v2"


class UnsafeHistoricalRecovery(ValueError):
    """Existing work or source evidence needs operator investigation."""


@dataclass(frozen=True, slots=True)
class RunEvidence:
    status: str
    trigger_type: str
    correlation_id: UUID
    snapshot_sha256: str | None


@dataclass(frozen=True, slots=True)
class ReleaseEvidence:
    input_schema_version: str
    output_schema_version: str


@dataclass(frozen=True, slots=True)
class LiveCoverageEvidence:
    run_id: UUID
    coverage: HistoryCoverage


@dataclass(frozen=True, slots=True)
class RecoveryEvidence:
    source_run: RunEvidence | None
    bootstrap_run: RunEvidence | None
    release: ReleaseEvidence | None
    candidate_ids: tuple[UUID, ...]
    live_coverages: tuple[LiveCoverageEvidence, ...]


@dataclass(frozen=True, slots=True)
class ExistingJob:
    job_id: UUID
    model_release_id: UUID
    input_snapshot_hash: str
    input_snapshot_json: Mapping[str, object]
    idempotency_key: str
    correlation_id: UUID


@dataclass(frozen=True, slots=True)
class ExistingDispatch:
    dispatch_id: UUID


@dataclass(frozen=True, slots=True)
class ExistingAudit:
    actor_type: str
    actor_service: str | None
    outcome: str
    reason_code: str | None
    correlation_id: UUID
    metadata: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class RecoveryCandidate:
    revision_id: UUID
    revision_number: int
    latest_revision_number: int
    event_superseded: bool
    anchor: FeatureObservation
    history: tuple[FeatureObservation, ...]
    job: ExistingJob | None
    dispatch: ExistingDispatch | None
    audit: ExistingAudit | None


class RecoveryTransaction(Protocol):
    def load(self) -> RecoveryCandidate: ...

    def create_work(
        self,
        *,
        job_id: UUID,
        dispatch_id: UUID,
        release_id: UUID,
        snapshot: FeatureSnapshot,
        correlation_id: UUID,
        audit_metadata: Mapping[str, object],
    ) -> None: ...


class HistoricalRecoveryStore(Protocol):
    def evidence(self) -> RecoveryEvidence: ...

    def transaction(self, revision_id: UUID) -> AbstractContextManager[RecoveryTransaction]: ...


class RecoverHistoricalPredictions:
    def __init__(
        self,
        store: HistoricalRecoveryStore,
        *,
        target_release_id: UUID,
        bootstrap_run_id: UUID,
        bootstrap_sha256: str,
        bootstrap_correlation_id: UUID,
        bootstrap_coverage: HistoryCoverage,
    ) -> None:
        self._store = store
        self._release_id = target_release_id
        self._bootstrap_run_id = bootstrap_run_id
        self._bootstrap_sha256 = bootstrap_sha256
        self._bootstrap_correlation_id = bootstrap_correlation_id
        self._bootstrap_coverage = bootstrap_coverage

    def run(
        self,
        *,
        apply: bool,
        max_new_jobs: int = 50,
        progress: Callable[[dict[str, int]], None] | None = None,
    ) -> dict[str, int]:
        if max_new_jobs < 1:
            raise ValueError("The recovery batch size must be positive.")
        evidence = self._store.evidence()
        source = evidence.source_run
        bootstrap = evidence.bootstrap_run
        release = evidence.release
        if (
            source is None
            or source.status != "succeeded"
            or source.trigger_type not in {"scheduled", "manual"}
            or bootstrap is None
            or bootstrap.status != "succeeded"
            or bootstrap.trigger_type != "backfill"
            or bootstrap.snapshot_sha256 != self._bootstrap_sha256
            or bootstrap.correlation_id != self._bootstrap_correlation_id
            or not self._bootstrap_coverage.complete
            or release is None
            or release.input_schema_version != INPUT_SCHEMA_VERSION
            or release.output_schema_version != OUTPUT_SCHEMA_VERSION
        ):
            raise UnsafeHistoricalRecovery("Source, bootstrap, or model evidence is invalid.")
        if not evidence.candidate_ids:
            raise UnsafeHistoricalRecovery("The source run has no matching skipped revisions.")
        coverages = merge_history_coverages(
            [self._bootstrap_coverage] + [item.coverage for item in evidence.live_coverages]
        )
        counts: Counter[str] = Counter(total=len(evidence.candidate_ids))
        for index, revision_id in enumerate(evidence.candidate_ids, 1):
            with self._store.transaction(revision_id) as transaction:
                self._process_candidate(
                    transaction,
                    evidence,
                    coverages,
                    counts,
                    apply=apply,
                    max_new_jobs=max_new_jobs,
                )
            if progress is not None and index % 50 == 0:
                progress(dict(counts))
        result = dict(counts)
        for key in ("superseded", "eligible", "created", "reused", "deferred"):
            result.setdefault(key, 0)
        return result

    def _process_candidate(
        self,
        transaction: RecoveryTransaction,
        evidence: RecoveryEvidence,
        coverages: tuple[HistoryCoverage, ...],
        counts: Counter[str],
        *,
        apply: bool,
        max_new_jobs: int,
    ) -> None:
        candidate = transaction.load()
        if (
            candidate.job is None
            and candidate.audit is None
            and (
                candidate.event_superseded
                or candidate.revision_number != candidate.latest_revision_number
            )
        ):
            counts["superseded"] += 1
            return
        coverage = coverage_for_anchor(candidate.anchor.event_time, coverages)
        decision = decide_prediction_snapshot(
            PredictionSnapshotRequest(
                anchor=candidate.anchor,
                history=candidate.history,
                coverage=coverage,
                input_schema_version=INPUT_SCHEMA_VERSION,
            )
        )
        if decision.snapshot is None:
            if candidate.job is not None or candidate.audit is not None:
                raise UnsafeHistoricalRecovery(
                    f"Existing work has no valid snapshot for {candidate.revision_id}."
                )
            counts[decision.decision.skip_reason or "ineligible"] += 1
            return
        if candidate.job is not None or candidate.audit is not None:
            self._validate_existing(candidate, decision.snapshot, evidence)
            counts["reused"] += 1
            return
        counts["eligible"] += 1
        if not apply:
            return
        if counts["created"] >= max_new_jobs:
            counts["deferred"] += 1
            return
        source = evidence.source_run
        if source is None or coverage is None:
            raise UnsafeHistoricalRecovery("Recovery coverage or source run is unavailable.")
        job_id, dispatch_id = uuid4(), uuid4()
        transaction.create_work(
            job_id=job_id,
            dispatch_id=dispatch_id,
            release_id=self._release_id,
            snapshot=decision.snapshot,
            correlation_id=source.correlation_id,
            audit_metadata={
                "source_run_id": str(SOURCE_RUN_ID),
                "bootstrap_run_id": str(self._bootstrap_run_id),
                "bootstrap_snapshot_sha256": self._bootstrap_sha256,
                "coverage_run_ids": [str(item.run_id) for item in evidence.live_coverages],
                "coverage_start": coverage.start.isoformat(),
                "coverage_end": coverage.end.isoformat(),
                "model_release_id": str(self._release_id),
                "input_snapshot_hash": decision.snapshot.sha256,
                "job_id": str(job_id),
                "dispatch_id": str(dispatch_id),
                "historical_no_alert": True,
            },
        )
        counts["created"] += 1

    def _validate_existing(
        self,
        candidate: RecoveryCandidate,
        snapshot: FeatureSnapshot,
        evidence: RecoveryEvidence,
    ) -> None:
        job, dispatch, audit = candidate.job, candidate.dispatch, candidate.audit
        source = evidence.source_run
        if job is None or dispatch is None or audit is None or source is None:
            raise UnsafeHistoricalRecovery(f"Existing work conflicts for {candidate.revision_id}.")
        expected_key = f"prediction:{candidate.revision_id}:{self._release_id}:{snapshot.sha256}"
        metadata = audit.metadata
        expected = {
            "source_run_id": str(SOURCE_RUN_ID),
            "bootstrap_run_id": str(self._bootstrap_run_id),
            "bootstrap_snapshot_sha256": self._bootstrap_sha256,
            "model_release_id": str(self._release_id),
            "input_snapshot_hash": snapshot.sha256,
            "job_id": str(job.job_id),
            "dispatch_id": str(dispatch.dispatch_id),
            "historical_no_alert": True,
        }
        if (
            job.model_release_id != self._release_id
            or job.input_snapshot_hash != snapshot.sha256
            or job.input_snapshot_json != dict(snapshot.values)
            or job.idempotency_key != expected_key
            or job.correlation_id != source.correlation_id
            or audit.actor_type != "system"
            or audit.actor_service != "operator-cli"
            or audit.outcome != "succeeded"
            or audit.reason_code != SKIP_REASON
            or audit.correlation_id != source.correlation_id
            or not isinstance(metadata, Mapping)
            or any(metadata.get(key) != value for key, value in expected.items())
            or not self._audited_coverage_matches(candidate, metadata, evidence)
        ):
            raise UnsafeHistoricalRecovery(f"Existing work conflicts for {candidate.revision_id}.")

    def _audited_coverage_matches(
        self,
        candidate: RecoveryCandidate,
        metadata: Mapping[str, object],
        evidence: RecoveryEvidence,
    ) -> bool:
        ids = metadata.get("coverage_run_ids")
        if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
            return False
        if len(ids) != len(set(ids)):
            return False
        available = {str(item.run_id): item.coverage for item in evidence.live_coverages}
        if any(item not in available for item in ids):
            return False
        merged = merge_history_coverages(
            [self._bootstrap_coverage] + [available[item] for item in ids]
        )
        coverage = coverage_for_anchor(candidate.anchor.event_time, merged)
        return (
            coverage is not None
            and evaluate_history_readiness(candidate.anchor.event_time, coverage).ready
            and metadata.get("coverage_start") == coverage.start.isoformat()
            and metadata.get("coverage_end") == coverage.end.isoformat()
        )
