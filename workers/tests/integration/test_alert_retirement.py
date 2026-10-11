import logging
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import insert, select

from quakestrike.infrastructure.database.alerts import SqlAlchemyAlertStore
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.tables import (
    alert_jobs,
    audit_logs,
    forecasts,
    job_dispatches,
)
from quakestrike.infrastructure.models.deterministic_test import DeterministicTestModel
from quakestrike.prediction_worker.worker import handle_prediction_command

from .test_prediction_worker import NOW, seed, store

pytestmark = pytest.mark.integration


def legacy(engine):
    command = seed(engine, trigger_type="backfill")
    assert (
        handle_prediction_command(
            command.to_message(),
            store=store(engine),
            model=DeterministicTestModel(),
            logger=logging.getLogger(__name__),
        )
        == "succeeded"
    )
    job_id, dispatch_id = uuid4(), uuid4()
    with engine.begin() as connection:
        forecast_id = connection.scalar(select(forecasts.c.forecast_id))
        connection.execute(
            insert(alert_jobs).values(
                alert_job_id=job_id,
                forecast_id=forecast_id,
                requested_at=NOW,
                message_snapshot="Legacy earthquake-only text",
                recipient_policy_snapshot={},
                expires_at=NOW + timedelta(hours=24),
                correlation_id=command.correlation_id,
            )
        )
        connection.execute(
            insert(job_dispatches).values(alert_job_id=job_id, dispatch_id=dispatch_id)
        )
    return job_id, dispatch_id


@pytest.mark.parametrize("expired", [False, True])
def test_explicit_retirement_preserves_legacy_content_and_commits_one_audit(
    migrated_engine, expired
):
    job_id, dispatch_id = legacy(migrated_engine)
    now = NOW + timedelta(hours=25) if expired else NOW
    alert_store = SqlAlchemyAlertStore(create_session_factory(migrated_engine), clock=lambda: now)
    preview = alert_store.preview_legacy_alerts()
    assert [row["alert_job_id"] for row in preview] == [str(job_id)]
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_jobs)).one().status == "pending"
    assert alert_store.retire_legacy_alerts((job_id,)) == 1
    assert alert_store.retire_legacy_alerts((job_id,)) == 0
    with migrated_engine.connect() as connection:
        job = connection.execute(select(alert_jobs)).one()
        assert job.status == ("expired" if expired else "failed")
        assert job.message_snapshot == "Legacy earthquake-only text"
        assert job.email_body_snapshot is None
        assert job.completed_at == now
        dispatch = connection.execute(
            select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch_id)
        ).one()
        assert dispatch.status == "stopped"
        audits = connection.execute(
            select(audit_logs).where(audit_logs.c.action == "retire_legacy_alert")
        ).all()
        assert len(audits) == 1
        assert audits[0].target_id == str(job_id)
        assert audits[0].reason_code == "legacy_content_retired"
        assert audits[0].metadata["previous_status"] == "pending"


def test_retirement_audit_failure_rolls_back_every_lifecycle_write(migrated_engine):
    from sqlalchemy import event

    job_id, dispatch_id = legacy(migrated_engine)
    alert_store = SqlAlchemyAlertStore(create_session_factory(migrated_engine), clock=lambda: NOW)

    def fail_audit(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO audit_logs"):
            raise RuntimeError("private database DETAIL")

    event.listen(migrated_engine, "before_cursor_execute", fail_audit)
    try:
        with pytest.raises(RuntimeError):
            alert_store.retire_legacy_alerts((job_id,))
    finally:
        event.remove(migrated_engine, "before_cursor_execute", fail_audit)
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_jobs)).one().status == "pending"
        assert (
            connection.execute(
                select(job_dispatches).where(job_dispatches.c.dispatch_id == dispatch_id)
            )
            .one()
            .status
            == "pending"
        )
        assert (
            connection.execute(
                select(audit_logs).where(audit_logs.c.action == "retire_legacy_alert")
            ).first()
            is None
        )


def test_retirement_refuses_active_claim_and_retained_submission_evidence(migrated_engine):
    from sqlalchemy import update

    from quakestrike.infrastructure.database.tables import alert_delivery_attempts, alert_recipients

    from .test_forecast_alert_evidence import recipient

    job_id, _ = legacy(migrated_engine)
    alert_store = SqlAlchemyAlertStore(create_session_factory(migrated_engine), clock=lambda: NOW)
    with migrated_engine.begin() as connection:
        connection.execute(
            update(alert_jobs).values(
                status="resolving",
                worker_execution_id=uuid4(),
                lease_expires_at=NOW + timedelta(seconds=60),
            )
        )
    assert alert_store.preview_legacy_alerts() == []
    with pytest.raises(ValueError, match="claims"):
        alert_store.retire_legacy_alerts((job_id,))
    recipient_id = recipient(migrated_engine, job_id)
    with migrated_engine.begin() as connection:
        connection.execute(
            update(alert_jobs).values(
                status="pending",
                worker_execution_id=None,
                lease_expires_at=None,
            )
        )
        connection.execute(update(alert_recipients).values(status="unknown"))
        connection.execute(
            insert(alert_delivery_attempts).values(
                delivery_attempt_id=uuid4(),
                recipient_id=recipient_id,
                attempt_number=1,
                provider="brevo",
                status="unknown",
                started_at=NOW,
                finished_at=NOW,
                provider_message_id="retained-legacy-reference",
                correlation_id=uuid4(),
                content_variant="general",
                eligibility_snapshot={},
                provider_evidence_snapshot={},
            )
        )
    assert alert_store.preview_legacy_alerts() == []
    with pytest.raises(ValueError, match="evidence"):
        alert_store.retire_legacy_alerts((job_id,))
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_delivery_attempts)).one().provider_message_id == (
            "retained-legacy-reference"
        )
