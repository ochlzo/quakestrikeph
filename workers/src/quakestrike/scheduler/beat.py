"""Celery Beat entry point for the durable five-minute ingestion tick."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from celery.beat import Scheduler, Service

from quakestrike.application.persistence import RunDispatchResult
from quakestrike.application.scheduling import (
    Clock,
    IdFactory,
    ScheduledRunStore,
    ScheduleIngestionPoll,
)
from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.logging.json_logging import log_event, log_exception_event
from quakestrike.infrastructure.queues.celery_app import (
    DURABLE_INGESTION_TICK,
    create_celery_app,
)
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import ConfiguredModelReleaseVerifier
from quakestrike.runtime import run_service


class DurableBeatScheduler(Scheduler):
    """Run the local database tick without publishing a Celery task from Beat."""

    @property
    def producer(self) -> None:
        """Prevent Celery's base tick from opening a broker connection."""

        return None

    def apply_entry(self, entry, producer=None) -> None:  # type: ignore[no-untyped-def]
        if entry.task != DURABLE_INGESTION_TICK:
            log_event(
                self._structured_logger,
                logging.ERROR,
                "Beat rejected an unrecognized scheduled entry",
                event_code="beat_schedule_rejected",
                context={"status": "rejected"},
            )
            return

        tick = self.app.conf.get("quakestrike_scheduled_ingestion_tick")
        if not callable(tick):
            log_event(
                self._structured_logger,
                logging.ERROR,
                "Beat has no configured durable ingestion tick callback",
                event_code="beat_tick_unconfigured",
                context={"status": "rejected"},
            )
            return

        try:
            result = tick()
        except Exception as error:
            log_exception_event(
                self._structured_logger,
                logging.ERROR,
                "Durable ingestion tick failed",
                event_code="scheduled_ingestion_tick_failed",
                error=error,
            )
        else:
            log_event(
                self._structured_logger,
                logging.INFO,
                "Durable ingestion tick completed",
                event_code="scheduled_ingestion_tick_completed",
                context={
                    "status": "created" if getattr(result, "created", False) else "reused",
                    "created": getattr(result, "created", None),
                    "run_id": getattr(result, "run_id", None),
                    "dispatch_id": getattr(result, "dispatch_id", None),
                },
            )

    @property
    def _structured_logger(self) -> logging.Logger:
        return logging.getLogger("scheduler-beat")


def run_scheduled_ingestion_tick(
    transactions: ScheduledRunStore,
    *,
    clock: Clock = lambda: datetime.now(UTC),
    id_factory: IdFactory = uuid4,
) -> RunDispatchResult:
    """Create or reuse the active scheduled run through the application boundary."""

    return ScheduleIngestionPoll(
        transactions,
        clock=clock,
        id_factory=id_factory,
    ).execute()


def run_beat(settings: Settings) -> int:
    """Run one Beat process with one durable local polling schedule."""

    engine = create_database_engine(settings.database_url)
    transactions = SqlAlchemyIngestionTransactions(
        create_session_factory(engine),
        model_release_verifier=ConfiguredModelReleaseVerifier(settings),
    )
    app = create_celery_app(
        settings,
        ingestion_tick=lambda: run_scheduled_ingestion_tick(transactions),
    )
    try:
        Service(app, scheduler_cls=DurableBeatScheduler).start()
    finally:
        engine.dispose()
    return 0


def main() -> int:
    return run_service("scheduler-beat", runtime=run_beat)


if __name__ == "__main__":
    raise SystemExit(main())
