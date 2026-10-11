"""Explicit, bounded operator actions; startup never retires or seeds work."""

from contextlib import contextmanager

from quakestrike.alert_worker.controlled import (
    run_controlled_alert,
    validate_controlled_environment,
)
from quakestrike.infrastructure.database.alerts import SqlAlchemyAlertStore
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.database.migration_state import AlembicMigrationStateGate
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.sms.iprog import IprogSmsSupport
from quakestrike.operator_output import print_json


@contextmanager
def alert_store(settings):
    engine = create_database_engine(settings.database_url, statement_timeout_ms=5000)
    try:
        yield SqlAlchemyAlertStore(create_session_factory(engine))
    finally:
        engine.dispose()


def retire_legacy_alerts(*, job_ids=(), apply=False):
    try:
        settings = Settings()
        if not AlembicMigrationStateGate(settings).check().ready:
            raise ValueError("Migration readiness is unavailable.")
        with alert_store(settings) as store:
            if apply:
                result = {"status": "retired", "retired": store.retire_legacy_alerts(job_ids)}
            else:
                result = {"status": "preview", "jobs": store.preview_legacy_alerts()}
        print_json({"action": "retire-legacy-alerts", **result})
        return 0
    except Exception:
        print_json({"action": "retire-legacy-alerts", "status": "unavailable"})
        return 2


def controlled_alert(payload, user_id, channels, *, reconcile=False):
    try:
        settings = Settings()
        validate_controlled_environment(settings)
        if not AlembicMigrationStateGate(settings).check().ready:
            raise ValueError("Migration readiness is unavailable.")
        token = settings.iprog_api_token
        with alert_store(settings) as store:
            result = run_controlled_alert(
                settings,
                payload,
                user_id,
                channels=channels,
                reconcile=reconcile,
                store=store,
                support=IprogSmsSupport(token.get_secret_value() if token else None),
            )
        print_json({"action": "controlled-alert", **result})
        return 0
    except Exception:
        print_json({"action": "controlled-alert", "status": "unavailable"})
        return 2
