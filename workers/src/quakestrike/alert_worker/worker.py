"""Identifier-only alert queue handler."""

import logging
from collections.abc import Mapping
from time import monotonic

from celery.exceptions import Reject
from pydantic import ValidationError

from quakestrike.application.alert_delivery import deliver_alert
from quakestrike.application.alerts import AlertStore, ResolveAlertRecipients, SmsSupport
from quakestrike.infrastructure.alert_readiness import alert_startup_gates
from quakestrike.infrastructure.alert_readiness import (
    configured_alert_providers as configured_alert_providers,
)
from quakestrike.infrastructure.database.alerts import SqlAlchemyAlertStore
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.logging.json_logging import log_event
from quakestrike.infrastructure.queues.alert_publisher import ALERT_TASK_NAME
from quakestrike.infrastructure.queues.celery_app import ALERT_QUEUE, create_celery_app
from quakestrike.infrastructure.queues.contracts import parse_alert_command
from quakestrike.infrastructure.sms.iprog import IprogSmsSupport
from quakestrike.runtime import run_service


def handle_alert_command(
    payload: object,
    *,
    store: AlertStore,
    support: SmsSupport,
    logger: logging.Logger,
    providers=None,
) -> str:
    deadline = monotonic() + 240
    if not isinstance(payload, Mapping):
        return "rejected"
    try:
        command = parse_alert_command(payload)
    except ValidationError:
        return "rejected"
    if providers is not None:
        store.maintain(command.dispatch_id, command.alert_job_id, command.correlation_id)
    result = ResolveAlertRecipients(store, support).execute(
        command.dispatch_id,
        command.alert_job_id,
        command.correlation_id,
        **({"clock": monotonic, "deadline": deadline} if providers is not None else {}),
    )
    log_event(
        logger,
        logging.INFO,
        "Alert resolution processed.",
        event_code="alert_resolution_processed",
        context={
            "dispatch_id": str(command.dispatch_id),
            "alert_job_id": str(command.alert_job_id),
            "correlation_id": str(command.correlation_id),
            "status": result.status,
            "reason": ",".join(result.support_failures) if result.support_failures else None,
        },
    )
    if providers is not None:
        claim = result.claim
        if result.status == "already_resolved":
            claim = store.claim(
                command.dispatch_id, command.alert_job_id, command.correlation_id, delivery=True
            )
            if isinstance(claim, str):
                return claim
        if claim is not None:

            def report(request, submission, outcome):
                log_event(
                    logger,
                    logging.INFO,
                    "Alert submission settled.",
                    event_code="alert_submission_settled",
                    context={
                        "alert_job_id": str(command.alert_job_id),
                        "recipient_id": str(request.recipient_id),
                        "attempt_id": str(request.attempt_id),
                        "correlation_id": str(command.correlation_id),
                        "provider": "iprog" if request.channel == "sms" else "brevo",
                        "status": submission.status,
                        "reason": "provider_reference_conflict"
                        if outcome == "conflict"
                        else submission.error_code,
                        **submission.evidence,
                    },
                )

            return deliver_alert(
                claim, store, support, providers, clock=monotonic, deadline=deadline, report=report
            )
    return result.status


def create_alert_app(settings, *, command_handler):
    app = create_celery_app(settings)

    @app.task(
        name=ALERT_TASK_NAME,
        acks_late=True,
        reject_on_worker_lost=True,
        acks_on_failure_or_timeout=False,
        soft_time_limit=300,
        time_limit=360,
    )
    def process_alert(payload):
        try:
            return command_handler(payload)
        except Exception:
            raise Reject("Alert processing failed.", requeue=True) from None

    return app


def create_alert_handler(settings, *, store, support, providers=None):
    if not settings.alert_resolution_enabled or not settings.alert_delivery_enabled:
        raise ValueError("Alert delivery runtime is disabled.")
    providers = configured_alert_providers(settings) if providers is None else providers

    def handle(payload):
        try:
            return handle_alert_command(
                payload,
                store=store,
                support=support,
                providers=providers,
                logger=logging.getLogger("alert-worker"),
            )
        except Exception:
            # PostgreSQL DETAIL can contain private rows even with hidden SQL parameters.
            raise RuntimeError("Alert processing is unavailable.") from None

    return handle


def run_alert(settings):
    if not settings.alert_resolution_enabled or not settings.alert_delivery_enabled:
        raise ValueError("Alert delivery runtime is disabled.")
    providers = configured_alert_providers(settings)

    def handle(payload):
        engine = create_database_engine(settings.database_url, statement_timeout_ms=5000)
        try:
            token = settings.iprog_api_token
            return create_alert_handler(
                settings,
                store=SqlAlchemyAlertStore(create_session_factory(engine)),
                support=IprogSmsSupport(token.get_secret_value() if token else None),
                providers=providers,
            )(payload)
        finally:
            engine.dispose()

    app = create_alert_app(settings, command_handler=handle)
    app.worker_main(
        [
            "worker",
            "--loglevel",
            settings.log_level,
            "--queues",
            ALERT_QUEUE,
            "--concurrency",
            "1",
            "--pool",
            "prefork",
            "--hostname",
            "alert-worker@%h",
        ]
    )
    return 0


def main():
    return run_service("alert-worker", runtime=run_alert, gate_factory=alert_startup_gates)


if __name__ == "__main__":
    raise SystemExit(main())
