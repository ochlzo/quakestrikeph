"""PostgreSQL history selection for the live feature contract."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quakestrike.application.features import HistorySelection
from quakestrike.domain.features import (
    HISTORY_WINDOW,
    FeatureObservation,
    HistoryCoverage,
)
from quakestrike.infrastructure.database.engine import SessionFactory
from quakestrike.infrastructure.database.tables import earthquake_event_revisions


class SqlAlchemyFeatureHistoryQuery:
    """Read the latest persisted revision once for each stable event.

    The caller supplies source coverage evidence.  This adapter intentionally
    does not decide that an old database row proves a complete source window.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def select_prior_history(
        self,
        anchor: FeatureObservation,
        *,
        coverage: HistoryCoverage | None = None,
    ) -> HistorySelection:
        with self._session_factory() as session:
            return self.select_prior_history_in_session(session, anchor, coverage=coverage)

    def select_history_at(
        self,
        anchor_time: datetime,
        *,
        coverage: HistoryCoverage | None = None,
    ) -> HistorySelection:
        """Read history for a declared boundary that has no anchor event."""

        with self._session_factory() as session:
            return self.select_history_at_in_session(session, anchor_time, coverage=coverage)

    @staticmethod
    def select_prior_history_in_session(
        session: Session,
        anchor: FeatureObservation,
        *,
        coverage: HistoryCoverage | None = None,
    ) -> HistorySelection:
        return SqlAlchemyFeatureHistoryQuery.select_history_at_in_session(
            session,
            anchor.event_time,
            coverage=coverage,
            excluded_event_id=anchor.event_id,
        )

    @staticmethod
    def select_history_at_in_session(
        session: Session,
        anchor_time: datetime,
        *,
        coverage: HistoryCoverage | None = None,
        excluded_event_id: object | None = None,
    ) -> HistorySelection:
        revisions = earthquake_event_revisions
        latest_revision = (
            select(
                revisions.c.event_id,
                func.max(revisions.c.revision_number).label("revision_number"),
            )
            .group_by(revisions.c.event_id)
            .subquery("latest_event_revision")
        )
        lower_bound = anchor_time - HISTORY_WINDOW
        statement = (
            select(revisions)
            .join(
                latest_revision,
                (latest_revision.c.event_id == revisions.c.event_id)
                & (latest_revision.c.revision_number == revisions.c.revision_number),
            )
            .where(
                revisions.c.event_time >= lower_bound,
                revisions.c.event_time < anchor_time,
            )
            .order_by(revisions.c.event_time.asc(), revisions.c.event_revision_id.asc())
        )
        if excluded_event_id is not None:
            statement = statement.where(revisions.c.event_id != excluded_event_id)
        rows = session.execute(statement).mappings()
        observations = tuple(_observation_from_row(row) for row in rows)
        return HistorySelection(observations=observations, coverage=coverage)


def _observation_from_row(row) -> FeatureObservation:
    return FeatureObservation(
        event_id=row["event_id"],
        event_time=row["event_time"],
        time_precision=row["source_time_precision"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        depth_km=row["depth_km"],
        magnitude=row["magnitude"],
    )


def observation_from_revision_request(event_id: object, revision) -> FeatureObservation:
    """Map the inward revision request to the domain feature input."""

    return FeatureObservation(
        event_id=event_id,
        event_time=revision.event_time,
        time_precision=revision.source_time_precision,
        latitude=revision.latitude,
        longitude=revision.longitude,
        depth_km=revision.depth_km,
        magnitude=revision.magnitude,
    )
