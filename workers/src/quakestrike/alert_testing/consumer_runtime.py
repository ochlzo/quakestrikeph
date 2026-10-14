"""Explicitly enabled isolated consumer; real transport requires Linux main thread."""

import logging
import os
import time
from uuid import uuid4

from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from quakestrike.alert_testing.application.delivery import Delivery
from quakestrike.alert_testing.application.reconciliation import Reconciliation
from quakestrike.alert_testing.application.sessions import Sessions
from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.infrastructure.accounts import (
    AccountAccessUnavailable,
    PostgresAccountReader,
)
from quakestrike.alert_testing.infrastructure.deliveries import RedisDeliveryStore
from quakestrike.alert_testing.infrastructure.redis import RedisSessionStore
from quakestrike.alert_testing.interface.consumer import Consumer
from quakestrike.domain.alerts import (
    DEFAULT_PUBLIC_BULLETIN_BASE_URL,
    validate_public_bulletin_base_url,
)
from quakestrike.infrastructure.email.brevo import BrevoEmailProvider
from quakestrike.infrastructure.geography.province import resolve_province_label
from quakestrike.infrastructure.logging.json_logging import configure_logging, log_event
from quakestrike.infrastructure.sms.iprog import IprogAlertProvider, IprogSmsSupport


class PollingDiagnostics:
    def __init__(self, logger):
        self.logger, self.failure = logger, None

    def __call__(self, event, attempt, outcome):
        if outcome.status == "unknown" and outcome.error_code is None:
            return
        reason = outcome.error_code if outcome.status == "unknown" else None
        if reason == self.failure or (reason and self.failure):
            return
        log_event(
            self.logger,
            logging.WARNING if reason else logging.INFO,
            "Test SMS polling unavailable" if reason else "Test SMS polling recovered",
            event_code="alert_testing_sms_poll_unavailable"
            if reason
            else "alert_testing_sms_poll_recovered",
            context={
                "operation": "sms_status",
                "provider": "iprog",
                "event_id": event,
                "job_id": event,
                "attempt_id": attempt,
                "reason": reason or self.failure,
            },
        )
        self.failure = reason


def main():
    if os.environ.get("ALERT_TEST_CONSUMER_ENABLED") != "true":
        raise SystemExit("Set ALERT_TEST_CONSUMER_ENABLED=true explicitly.")
    redis_url = os.environ.get("ALERT_TEST_REDIS_URL")
    account_url = os.environ.get("ALERT_TEST_DATABASE_URL")
    if not redis_url or not account_url:
        raise SystemExit("Configure explicit test Redis and restricted account URLs.")
    client = Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        retry=Retry(NoBackoff(), 0),
    )
    engine = create_engine(
        account_url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=2,
        connect_args={"connect_timeout": 2},
        hide_parameters=True,
    )
    sessions = Sessions(RedisSessionStore(client))
    store = RedisDeliveryStore(
        client,
        validate_public_bulletin_base_url(
            os.environ.get("ALERT_TEST_PUBLIC_BULLETIN_URL", DEFAULT_PUBLIC_BULLETIN_BASE_URL)
        ),
    )
    token = os.environ.get("ALERT_TEST_IPROG_TOKEN")
    delivery = Delivery(
        sessions,
        store,
        PostgresAccountReader(engine),
        IprogSmsSupport(token),
        {
            "sms": IprogAlertProvider(token),
            "email": BrevoEmailProvider(
                os.environ.get("ALERT_TEST_BREVO_API_KEY"),
                os.environ.get("ALERT_TEST_BREVO_SENDER_EMAIL"),
                os.environ.get("ALERT_TEST_BREVO_SENDER_NAME"),
            ),
        },
        resolve_province_label,
    )
    consumer = Consumer(store, delivery, str(uuid4()))
    logger = configure_logging("alert-testing-consumer")
    reconciliation = Reconciliation(
        store, delivery.providers["sms"], report=PollingDiagnostics(logger)
    )
    unavailable = None
    try:
        while True:
            try:
                session = sessions.read()
                if session.get("status") == "active":
                    owner = session["session_id"]
                    store.recover_publications(owner)
                    consumed = consumer.once(owner)
                    reconciliation.once(owner)
                else:
                    consumed = False
                if unavailable is not None and (unavailable == "redis_unavailable" or consumed):
                    log_event(
                        logger,
                        logging.INFO,
                        "Test consumer dependency recovered",
                        event_code="alert_testing_consumer_dependency_recovered",
                        context={"operation": "consume", "reason": unavailable},
                    )
                    unavailable = None
                if consumed:
                    continue
            except SessionConflict:
                pass
            except (RedisError, SQLAlchemyError, AccountAccessUnavailable) as error:
                reason = (
                    "redis_unavailable" if isinstance(error, RedisError) else "accounts_unavailable"
                )
                if unavailable != reason:
                    log_event(
                        logger,
                        logging.WARNING,
                        "Test consumer dependency unavailable",
                        event_code="alert_testing_consumer_dependency_unavailable",
                        context={"operation": "consume", "reason": reason},
                    )
                unavailable = reason
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        client.close()
        engine.dispose()


if __name__ == "__main__":
    main()
