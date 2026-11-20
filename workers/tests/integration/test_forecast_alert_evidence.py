from __future__ import annotations

import logging
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import IntegrityError, ProgrammingError

from quakestrike.infrastructure.database.tables import (
    alert_delivery_attempts,
    alert_jobs,
    alert_recipients,
    users,
)
from quakestrike.infrastructure.models.deterministic_test import DeterministicTestModel
from quakestrike.prediction_worker.worker import handle_prediction_command

from .test_prediction_worker import NOW, seed, store

pytestmark = pytest.mark.integration


def completed_alert(engine):
    command = seed(engine)
    assert (
        handle_prediction_command(
            command.to_message(),
            store=store(engine),
            model=DeterministicTestModel(),
            logger=logging.getLogger(__name__),
        )
        == "succeeded"
    )
    with engine.connect() as connection:
        return connection.scalar(select(alert_jobs.c.alert_job_id))


def recipient(engine, alert_id, *, channel="email"):
    user_id, recipient_id = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(users).values(
                user_id=user_id,
                clerk_user_id=str(user_id),
                display_name="Test reader",
                email=f"{user_id}@example.invalid",
            )
        )
        connection.execute(
            insert(alert_recipients).values(
                recipient_id=recipient_id,
                alert_job_id=alert_id,
                user_id=user_id,
                channel=channel,
                destination_snapshot=f"{user_id}@example.invalid",
                eligibility_snapshot={"policy_version": "automatic_forecast_alert_v1"},
                delivery_idempotency_key=str(recipient_id),
            )
        )
    return recipient_id


def test_every_content_snapshot_is_immutable_after_prediction_completion(migrated_engine):
    alert_id = completed_alert(migrated_engine)
    for column in (
        "message_snapshot",
        "email_subject_snapshot",
        "email_body_snapshot",
        "nearby_message_snapshot",
        "nearby_email_subject_snapshot",
        "nearby_email_body_snapshot",
    ):
        with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
            connection.execute(
                update(alert_jobs)
                .where(alert_jobs.c.alert_job_id == alert_id)
                .values({column: "Replacement content"})
            )
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            update(alert_jobs)
            .where(alert_jobs.c.alert_job_id == alert_id)
            .values(content_provenance_snapshot={"replacement": True})
        )


def test_attempt_keeps_variant_evidence_and_allows_only_one_sending_call(migrated_engine):
    recipient_id = recipient(migrated_engine, completed_alert(migrated_engine))
    attempt_id = uuid4()
    evidence = {"nearby_alerts_only": True, "calculated_distance_km": 25}
    values = dict(
        recipient_id=recipient_id,
        attempt_number=1,
        provider="brevo",
        correlation_id=uuid4(),
        content_variant="nearby",
        eligibility_snapshot=evidence,
    )
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(alert_delivery_attempts).values(delivery_attempt_id=attempt_id, **values)
        )
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            insert(alert_delivery_attempts).values(
                delivery_attempt_id=uuid4(),
                **{**values, "attempt_number": 2},
            )
        )
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            update(alert_delivery_attempts)
            .where(alert_delivery_attempts.c.delivery_attempt_id == attempt_id)
            .values(content_variant="general", eligibility_snapshot={})
        )


def test_early_brevo_callback_binds_attempt_and_same_second_delivery_wins(migrated_engine):
    recipient_id = recipient(migrated_engine, completed_alert(migrated_engine))
    attempt_id = uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            update(alert_recipients)
            .where(alert_recipients.c.recipient_id == recipient_id)
            .values(
                status="sending",
                processing_lease_expires_at=NOW + timedelta(minutes=5),
                worker_execution_id=uuid4(),
            )
        )
        connection.execute(
            insert(alert_delivery_attempts).values(
                delivery_attempt_id=attempt_id,
                recipient_id=recipient_id,
                attempt_number=1,
                provider="brevo",
                started_at=NOW,
                correlation_id=uuid4(),
                content_variant="general",
                eligibility_snapshot={"account_status": "active"},
            )
        )
    callback = text(
        "SELECT quakestrike_reconcile_brevo_delivery(:attempt, :reference, :status, :at, NULL)"
    )
    args = dict(attempt=attempt_id, reference="<known-brevo-reference>", at=NOW)
    with migrated_engine.begin() as connection:
        assert connection.scalar(callback, {**args, "status": "accepted"}) == "applied"
        assert connection.scalar(callback, {**args, "status": "delivered"}) == "applied"
        assert connection.scalar(callback, {**args, "status": "accepted"}) == "ignored"
        assert (
            connection.scalar(callback, {**args, "status": "failed", "at": NOW + timedelta(days=2)})
            == "ignored"
        )
        assert (
            connection.scalar(callback, {**args, "status": "delivered", "reference": "conflict"})
            == "conflict"
        )
    with migrated_engine.connect() as connection:
        attempt = connection.execute(select(alert_delivery_attempts)).one()
        resolved = connection.execute(select(alert_recipients)).one()
    assert attempt.provider_message_id == "<known-brevo-reference>"
    assert attempt.status == resolved.status == "delivered"
    assert attempt.finished_at is not None
    assert resolved.worker_execution_id is None
    assert resolved.delivered_at == NOW


def test_unmatched_callbacks_do_not_claim_success_or_public_execution(migrated_engine):
    with migrated_engine.begin() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT quakestrike_reconcile_brevo_delivery("
                    "NULL, 'unmatched', 'delivered', now(), NULL)"
                )
            )
            == "uncorrelated"
        )
        assert (
            connection.scalar(
                text("""
            SELECT count(*) FROM pg_proc p
            CROSS JOIN LATERAL aclexplode(p.proacl) acl
            WHERE p.proname = 'quakestrike_reconcile_brevo_delivery'
              AND acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
        """)
            )
            == 0
        )


@pytest.mark.parametrize(
    "probability,percentage,likelihood",
    [
        (0, "0%", "Low"),
        (0.0049, "<1%", "Low"),
        (0.005, "1%", "Low"),
        (0.125, "13%", "Low"),
        (0.295, "30%", "Low"),
        (0.3, "30%", "Medium"),
        (0.695, "70%", "Medium"),
        (0.7, "70%", "High"),
        (0.995, ">99%", "High"),
        (0.999, ">99%", "High"),
        (1, "100%", "High"),
    ],
)
def test_prediction_content_matches_bulletin_probability_rules(
    migrated_engine,
    probability,
    percentage,
    likelihood,
):
    class Model(DeterministicTestModel):
        def predict(self, features):
            return {**super().predict(features), "m1_probability": probability}

    command = seed(migrated_engine)
    assert (
        handle_prediction_command(
            command.to_message(),
            store=store(migrated_engine),
            model=Model(),
            logger=logging.getLogger(__name__),
        )
        == "succeeded"
    )
    with migrated_engine.connect() as connection:
        message = connection.scalar(select(alert_jobs.c.message_snapshot))
    assert f"Chance of further M1.0+ activity: {percentage}\nLikelihood: {likelihood}\n" in message


@pytest.mark.parametrize(
    "latitude,longitude,label,source",
    [
        ("6.350000", "125.533330", "near Davao Occidental", "geonames_nearest_province"),
        ("3.849410", "119.402460", "near Tawi-Tawi", "geonames_nearest_province"),
        ("3.849409", "119.402460", "0002 km unchanged PHIVOLCS source", "phivolcs"),
        ("0.000000", "0.000000", "0002 km unchanged PHIVOLCS source", "phivolcs"),
    ],
)
def test_prediction_freezes_near_province_or_unchanged_source_at_lookup_limit(
    migrated_engine,
    latitude,
    longitude,
    label,
    source,
):
    command = seed(
        migrated_engine,
        latitude=Decimal(latitude),
        longitude=Decimal(longitude),
        source_location="0002 km unchanged PHIVOLCS source",
    )
    assert (
        handle_prediction_command(
            command.to_message(),
            store=store(migrated_engine),
            model=DeterministicTestModel(),
            logger=logging.getLogger(__name__),
        )
        == "succeeded"
    )
    with migrated_engine.connect() as connection:
        alert = connection.execute(select(alert_jobs)).one()
    assert alert.content_provenance_snapshot["location_label"] == label
    assert alert.content_provenance_snapshot["location_source"] == source
    assert f"Location: {label}\n" in alert.message_snapshot
    assert alert.content_provenance_snapshot["geographic_dataset_version"]


def test_email_keeps_optional_outputs_unavailable(migrated_engine):
    class Model(DeterministicTestModel):
        def predict(self, features):
            return {
                **super().predict(features),
                "radius_median": None,
                "maximum_q05": None,
                "maximum_q50": None,
                "maximum_q95": None,
            }

    command = seed(migrated_engine)
    assert (
        handle_prediction_command(
            command.to_message(),
            store=store(migrated_engine),
            model=Model(),
            logger=logging.getLogger(__name__),
        )
        == "succeeded"
    )
    with migrated_engine.connect() as connection:
        body = connection.scalar(select(alert_jobs.c.email_body_snapshot))
    assert "Possible further activity radius: Unavailable" in body
    assert "Possible maximum magnitude: Unavailable" in body
    assert "not shaking distance or a safety boundary" in body


def test_restricted_worker_and_callback_grants_do_not_allow_unrelated_data(migrated_engine):
    alert_id = completed_alert(migrated_engine)
    provisioning = (
        Path(__file__).resolve().parents[3] / "database/initialization/provision-roles.sh"
    ).read_text(encoding="utf-8")
    worker_block = provisioning.split("  grant-worker)", 1)[1]
    worker_sql = re.search(r"<<'SQL'\n(.*?)\nSQL", worker_block, re.S).group(1)
    role_state_query = text(
        "SELECT rolname, rolcanlogin FROM pg_roles "
        "WHERE rolname IN ('quakestrike_worker', 'quakestrike_backend') ORDER BY rolname"
    )
    with migrated_engine.connect() as connection:
        original_roles = connection.execute(role_state_query).all()
        connection.rollback()
        transaction = connection.begin()
        try:
            connection.execute(
                text("""
                DO $$ BEGIN
                  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quakestrike_worker') THEN
                    CREATE ROLE quakestrike_worker NOLOGIN;
                  END IF;
                  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quakestrike_backend') THEN
                    CREATE ROLE quakestrike_backend NOLOGIN;
                  END IF;
                END $$;
                GRANT USAGE ON SCHEMA public TO quakestrike_worker, quakestrike_backend;
                GRANT EXECUTE ON FUNCTION
                  quakestrike_reconcile_brevo_delivery(uuid,text,text,timestamptz,text)
                  TO quakestrike_backend;
            """)
            )
            connection.execute(text(worker_sql))
            connection.execute(text("SET LOCAL ROLE quakestrike_worker"))
            assert connection.scalar(select(alert_jobs.c.alert_job_id)) == alert_id
            connection.execute(select(users.c.email))
            with pytest.raises(ProgrammingError), connection.begin_nested():
                connection.execute(select(users.c.display_name))
            with pytest.raises(ProgrammingError), connection.begin_nested():
                connection.execute(update(users).values(sms_enabled=True))
            with pytest.raises(ProgrammingError), connection.begin_nested():
                connection.execute(update(alert_jobs).values(message_snapshot="Replacement"))
            connection.execute(text("SET LOCAL ROLE quakestrike_backend"))
            assert (
                connection.scalar(
                    text(
                        "SELECT quakestrike_reconcile_brevo_delivery("
                        "NULL, 'unmatched', 'delivered', now(), NULL)"
                    )
                )
                == "uncorrelated"
            )
            with pytest.raises(ProgrammingError), connection.begin_nested():
                connection.execute(select(alert_recipients.c.recipient_id))
            with pytest.raises(ProgrammingError), connection.begin_nested():
                connection.execute(update(alert_delivery_attempts).values(status="failed"))
        finally:
            transaction.rollback()
        assert connection.execute(role_state_query).all() == original_roles
