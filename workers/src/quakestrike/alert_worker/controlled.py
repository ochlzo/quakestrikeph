"""One explicitly selected disposable fixture; never an ordinary backlog consumer."""

import logging
import re
from types import SimpleNamespace
from urllib.parse import urlsplit

from pydantic import ValidationError

from quakestrike.alert_worker.worker import configured_alert_providers, handle_alert_command
from quakestrike.application.sms_polling import poll_iprog_deliveries
from quakestrike.infrastructure.queues.contracts import parse_alert_command


def validate_controlled_environment(settings):
    database, redis = urlsplit(settings.database_url), urlsplit(settings.redis_url)
    if (
        database.hostname != "postgres-test"
        or database.path != "/quakestrike_test"
        or database.port not in (None, 5432)
        or redis.hostname != "redis-test"
        or redis.path != "/0"
        or redis.port not in (None, 6379)
    ):
        raise ValueError("Controlled alerts require the dedicated disposable environment.")


class RestrictedProvider:
    def __init__(self, provider, channel, destination):
        self.provider, self.channel, self.destination = provider, channel, destination
        self.submitted = 0

    def submit(self, request):
        if (
            request.channel != self.channel
            or request.destination != self.destination
            or self.submitted >= 1
        ):
            raise ValueError("Controlled submission scope or budget is exhausted.")
        self.submitted += 1
        return self.provider.submit(request)


def run_controlled_alert(
    settings, payload, user_id, *, channels, store, support, providers=None, reconcile=False
):
    validate_controlled_environment(settings)
    if not channels or set(channels) - {"sms", "email"} or len(set(channels)) != len(channels):
        raise ValueError("Select distinct controlled delivery channels.")
    try:
        command = parse_alert_command(payload)
    except (ValidationError, TypeError):
        raise ValueError("Controlled fixture command is invalid.") from None
    destinations = {}
    for channel in channels:
        configured = getattr(settings, f"alert_test_{channel}_destination")
        if configured is None:
            raise ValueError("Controlled destination authorization is unavailable.")
        destination = configured.get_secret_value()
        valid = (
            re.fullmatch(r"\+639[0-9]{9}", destination)
            if channel == "sms"
            else (
                3 <= len(destination) <= 320
                and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", destination)
            )
        )
        if not valid:
            raise ValueError("Controlled destination authorization is invalid.")
        destinations[channel] = destination
    configured = configured_alert_providers(settings, channels=channels)
    providers = configured if providers is None else providers
    if set(providers) != set(channels):
        raise ValueError("Controlled provider channels do not match selection.")
    try:
        valid_fixture = store.controlled_fixture_is_valid(
            command, user_id, destinations, submitting=not reconcile
        )
    except Exception:
        raise RuntimeError("Controlled fixture verification is unavailable.") from None
    if not valid_fixture:
        raise ValueError("Selected fixture is not authorized for a new submission.")
    if reconcile:
        outcomes = []
        scoped = SimpleNamespace(
            iprog_poll_candidates=lambda **kwargs: store.iprog_poll_candidates(
                **kwargs, alert_job_id=command.alert_job_id
            ),
            reconcile_delivery=store.reconcile_delivery,
            maintain=store.maintain,
        )
        try:
            polled = (
                poll_iprog_deliveries(
                    scoped,
                    providers["sms"],
                    limit=1,
                    report=lambda candidate, result, outcome: outcomes.append(outcome),
                ).processed
                if "sms" in channels
                else 0
            )
            store.maintain(command.dispatch_id, command.alert_job_id, command.correlation_id)
            if "poll_reconciliation_unavailable" in outcomes:
                raise RuntimeError("Controlled reconciliation is unavailable.")
        except Exception:
            raise RuntimeError("Controlled reconciliation is unavailable.") from None
        return {
            "status": "reconciled",
            "polled": polled,
            "submitted": {channel: 0 for channel in channels},
        }
    restricted = {
        channel: RestrictedProvider(providers[channel], channel, destinations[channel])
        for channel in channels
    }
    try:
        status = handle_alert_command(
            command.to_message(),
            store=store,
            support=support,
            providers=restricted,
            logger=logging.getLogger("controlled-alert"),
        )
    except Exception:
        raise RuntimeError("Controlled alert processing is unavailable.") from None
    return {
        "status": status,
        "submitted": {channel: provider.submitted for channel, provider in restricted.items()},
    }
