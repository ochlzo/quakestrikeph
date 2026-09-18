from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select

from quakestrike.application.bootstrap import run_bootstrap
from quakestrike.application.reconciliation import ReconcileSourceRows, ReconciliationDiagnostic
from quakestrike.domain.features import PredictionSkipReason
from quakestrike.infrastructure.bootstrap import (
    evaluate_bootstrap_readiness,
    load_bootstrap_snapshot,
    prepare_run_manifest,
    write_run_manifest,
)
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.database.tables import (
    earthquake_bulletin_event_identities,
    earthquake_event_revisions,
    earthquake_events,
    ingestion_run_inputs,
    ingestion_runs,
    job_dispatches,
    model_releases,
    prediction_jobs,
)

pytestmark = pytest.mark.integration
FIXTURE = Path(__file__).parents[1] / "fixtures" / "bootstrap" / "historical_snapshot.json"


class VerifiedReleaseGate:
    def __init__(self, release_id):
        self.release_id = release_id

    def is_verified(self, release_id) -> bool:
        return release_id == self.release_id


class Reporter:
    def __init__(self) -> None:
        self.diagnostics: list[ReconciliationDiagnostic] = []

    def report(self, diagnostic: ReconciliationDiagnostic) -> None:
        self.diagnostics.append(diagnostic)


def test_bootstrap_is_resumable_and_keeps_prediction_dispatch_in_scope(
    migrated_engine, tmp_path: Path
) -> None:
    release_id = uuid4()
    previous_run_id = uuid4()
    previous_event_id = uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(ingestion_runs).values(
                run_id=previous_run_id,
                trigger_type="scheduled",
                status="succeeded",
                started_at=datetime(2026, 9, 17, tzinfo=UTC),
                finished_at=datetime(2026, 9, 17, tzinfo=UTC),
                correlation_id=uuid4(),
            )
        )
        connection.execute(
            insert(model_releases).values(
                model_release_id=release_id,
                version_label="SEIS 1.0",
                artifact_manifest_uri="model-artifacts/seis-1.0/manifest.json",
                artifact_manifest_hash="a" * 64,
                input_schema_version="quakestrike.prediction-input.v1",
                output_schema_version="quakestrike.prediction-output.v1",
            )
        )
        connection.execute(
            insert(earthquake_events).values(
                event_id=previous_event_id,
                first_seen_run_id=previous_run_id,
                last_seen_run_id=previous_run_id,
            )
        )
        connection.execute(
            insert(earthquake_bulletin_event_identities).values(
                source_bulletin_id="2026_0827_1200_B1",
                event_id=previous_event_id,
            )
        )
        connection.execute(
            insert(earthquake_event_revisions).values(
                event_revision_id=uuid4(),
                event_id=previous_event_id,
                revision_number=1,
                ingestion_run_id=previous_run_id,
                source_bulletin_id="2026_0827_1200_B1",
                source_event_group_id="2026_0827_1200",
                source_url=(
                    "https://earthquake.phivolcs.dost.gov.ph/"
                    "2026_Earthquake_Information/August/2026_0827_1200_B1.html"
                ),
                source_time_precision="minute",
                event_time=datetime(2026, 8, 27, 4, tzinfo=UTC),
                latitude="14.100000",
                longitude="121.100000",
                depth_km="12.000",
                magnitude="1.00",
                location_description="Sanitized original revision",
            )
        )

    snapshot = load_bootstrap_snapshot(FIXTURE)
    manifest = prepare_run_manifest(snapshot, tmp_path / "historical.json.bootstrap.json")
    store = SqlAlchemyIngestionTransactions(
        create_session_factory(migrated_engine),
        model_release_verifier=VerifiedReleaseGate(release_id),
    )
    reporter = Reporter()

    def snapshot_loader(*, heartbeat=None):
        assert heartbeat is not None and heartbeat() is True
        return snapshot.parsed

    reconciler = ReconcileSourceRows(
        store=store,
        source_loader=snapshot_loader,
        diagnostic_reporter=reporter,
        model_release_id=release_id,
        history_coverage=snapshot.coverage.history_coverage(),
    )
    first = run_bootstrap(
        store=store,
        reconciler=reconciler,
        run_id=_manifest_uuid(manifest, "run_id"),
        correlation_id=_manifest_uuid(manifest, "correlation_id"),
        manifest=manifest,
        write_manifest=lambda value: write_run_manifest(
            tmp_path / "historical.json.bootstrap.json", value
        ),
    )

    assert first.state.status == "succeeded"
    assert first.state.events_found == 8
    assert first.state.events_inserted == 3
    assert first.state.events_revised == 1
    assert first.state.events_rejected == 4
    assert {item.code for item in reporter.diagnostics} == {
        "DETAIL_FETCH_FAILED",
        "DETAIL_NON_HTML_RESPONSE",
        "INVALID_SOURCE_URL",
        "INVALID_NUMERIC_VALUE",
        "INVALID_CATALOG_TIMESTAMP",
        "INVALID_CATALOG_ROW",
    }

    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(earthquake_events)) == 4
        assert connection.scalar(select(func.count()).select_from(earthquake_event_revisions)) == 5
        assert connection.scalar(select(func.count()).select_from(ingestion_run_inputs)) == 8
        assert connection.scalar(select(func.count()).select_from(prediction_jobs)) == 1
        assert connection.scalar(select(func.count()).select_from(job_dispatches)) == 1
        assert (
            connection.scalar(
                select(func.count())
                .select_from(job_dispatches)
                .where(job_dispatches.c.ingestion_run_id.is_not(None))
            )
            == 0
        )
        assert (
            connection.scalar(
                select(func.count())
                .select_from(earthquake_event_revisions)
                .where(
                    earthquake_event_revisions.c.prediction_skip_reason.in_(
                        (
                            PredictionSkipReason.BELOW_M1.value,
                            PredictionSkipReason.HISTORY_STARTS_AFTER_REQUIRED_WINDOW.value,
                        )
                    )
                )
            )
            == 3
        )

    diagnostic_count = len(reporter.diagnostics)
    second = run_bootstrap(
        store=store,
        reconciler=reconciler,
        run_id=_manifest_uuid(manifest, "run_id"),
        correlation_id=_manifest_uuid(manifest, "correlation_id"),
        manifest=manifest,
        write_manifest=lambda value: write_run_manifest(
            tmp_path / "historical.json.bootstrap.json", value
        ),
    )
    assert second.reconciliation_status == "already_succeeded"
    assert len(reporter.diagnostics) == diagnostic_count

    manifest = json.loads((tmp_path / "historical.json.bootstrap.json").read_text(encoding="utf-8"))
    assert manifest["diagnostics"]["DETAIL_FETCH_FAILED"] == 1
    assert manifest["diagnostics"]["INVALID_CATALOG_ROW"] == 1
    readiness = evaluate_bootstrap_readiness(snapshot, manifest, second.state)
    assert readiness.ready is True


def _manifest_uuid(manifest: dict[str, object], key: str) -> UUID:
    return UUID(str(manifest[key]))
