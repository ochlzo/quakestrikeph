from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from quakestrike.infrastructure.database.alerts import SqlAlchemyAlertStore
from quakestrike.infrastructure.database.tables import alert_delivery_attempts

from .test_alert_resolution import Support, account, queued
from .test_prediction_worker import NOW

pytestmark = pytest.mark.integration


def fixture_settings():
    return SimpleNamespace(
        database_url="postgresql+psycopg://worker:test@postgres-test:5432/quakestrike_test",
        redis_url="redis://redis-test:6379/0",
        iprog_api_token=SecretStr("simulated-token"),
        brevo_api_key=None,
        brevo_sender_email=None,
        brevo_sender_name=None,
        alert_test_sms_destination=SecretStr("+639171234567"),
        alert_test_email_destination=None,
    )


def command(dispatch):
    return {
        "message_version": 1,
        "dispatch_id": str(dispatch.dispatch_id),
        "alert_job_id": str(dispatch.alert_job_id),
        "correlation_id": str(dispatch.correlation_id),
    }


def test_finite_sms_only_runner_requires_exact_fixture_and_never_repeats_submission(
    migrated_engine,
):
    from quakestrike.alert_worker.controlled import run_controlled_alert

    dispatch, sessions = queued(migrated_engine)
    user_id = account(migrated_engine, email_enabled=False)
    sent = []

    class Sms:
        def submit(self, request):
            sent.append(request.destination)
            return SimpleNamespace(status="unknown", reference="uncertain-fixture-reference")

    dependencies = dict(
        store=SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
        support=Support(),
        providers={"sms": Sms()},
    )
    result = run_controlled_alert(
        fixture_settings(),
        command(dispatch),
        user_id,
        channels=("sms",),
        **dependencies,
    )
    assert result["submitted"] == {"sms": 1}
    assert sent == ["+639171234567"]
    with pytest.raises(ValueError, match="fixture"):
        run_controlled_alert(
            fixture_settings(),
            command(dispatch),
            user_id,
            channels=("sms",),
            **dependencies,
        )
    assert len(sent) == 1
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_delivery_attempts)).one().status == "unknown"


@pytest.mark.parametrize("mismatch", ["database", "destination", "ordinary_account"])
def test_finite_runner_rejects_scope_mismatch_before_any_attempt(migrated_engine, mismatch):
    from quakestrike.alert_worker.controlled import run_controlled_alert

    dispatch, sessions = queued(migrated_engine)
    user_id = account(migrated_engine, email_enabled=False)
    settings = fixture_settings()
    if mismatch == "database":
        settings.database_url = "postgresql+psycopg://worker:test@postgres:5432/quakestrike"
    elif mismatch == "destination":
        settings.alert_test_sms_destination = SecretStr("+639171234568")
    else:
        account(migrated_engine, email_enabled=False, mobile_number="+639171234568")

    class Never:
        def submit(self, request):
            pytest.fail("The scope guard must run before submission.")

    with pytest.raises(ValueError):
        run_controlled_alert(
            settings,
            command(dispatch),
            user_id,
            channels=("sms",),
            store=SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
            support=Support(),
            providers={"sms": Never()},
        )
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_delivery_attempts)).first() is None


def test_controlled_reconciliation_polls_only_selected_job_without_resubmission(migrated_engine):
    from quakestrike.alert_worker.controlled import run_controlled_alert
    from quakestrike.application.sms_polling import SmsOutcome

    dispatch, sessions = queued(migrated_engine)
    user_id = account(migrated_engine, email_enabled=False)
    submitted, polled = [], []

    class Sms:
        def submit(self, request):
            submitted.append(request.attempt_id)
            return SimpleNamespace(status="accepted", reference="selected-reference")

        def poll(self, reference):
            polled.append(reference)
            return SmsOutcome("delivered")

    dependencies = dict(
        store=SqlAlchemyAlertStore(sessions, clock=lambda: NOW),
        support=Support(),
        providers={"sms": Sms()},
    )
    run_controlled_alert(
        fixture_settings(), command(dispatch), user_id, channels=("sms",), **dependencies
    )
    result = run_controlled_alert(
        fixture_settings(),
        command(dispatch),
        user_id,
        channels=("sms",),
        reconcile=True,
        **dependencies,
    )
    assert result["polled"] == 1 and result["submitted"] == {"sms": 0}
    assert polled == ["selected-reference"] and len(submitted) == 1
    with migrated_engine.connect() as connection:
        assert connection.execute(select(alert_delivery_attempts)).one().status == "delivered"
