"""Stored revisions provide details only for unchanged live catalog rows."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, update

from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.repositories import SqlAlchemyIngestionTransactions
from quakestrike.infrastructure.database.tables import (
    earthquake_bulletin_event_identities,
    earthquake_event_revisions,
    earthquake_events,
    ingestion_runs,
)
from quakestrike.infrastructure.phivolcs.parser import parse_current_catalog, parse_detail_page

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures" / "phivolcs"
CATALOG_URL = "https://earthquake.phivolcs.dost.gov.ph/"


class VerifiedReleaseGate:
    def is_verified(self, release_id) -> bool:
        return True


def test_reuse_requires_matching_catalog_fields_and_accepted_detail(migrated_engine) -> None:
    row = parse_current_catalog(
        (FIXTURES / "current_catalog.html").read_bytes(), CATALOG_URL
    ).accepted_rows[0]
    detail = parse_detail_page((FIXTURES / "bulletin_detail.html").read_bytes())
    run_id = uuid4()
    event_id = uuid4()
    revision_id = uuid4()
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(ingestion_runs).values(
                run_id=run_id,
                trigger_type="scheduled",
                status="succeeded",
                started_at=now,
                finished_at=now,
                correlation_id=uuid4(),
            )
        )
        connection.execute(
            insert(earthquake_events).values(
                event_id=event_id, first_seen_run_id=run_id, last_seen_run_id=run_id
            )
        )
        connection.execute(
            insert(earthquake_bulletin_event_identities).values(
                source_bulletin_id=row.source_bulletin_id, event_id=event_id
            )
        )
        connection.execute(
            insert(earthquake_event_revisions).values(
                event_revision_id=revision_id,
                event_id=event_id,
                revision_number=1,
                ingestion_run_id=run_id,
                source_bulletin_id=row.source_bulletin_id,
                source_event_group_id=row.source_event_group_id,
                source_url=row.source_url,
                source_time_precision="second",
                event_time=detail.occurred_at,
                latitude=row.latitude,
                longitude=row.longitude,
                depth_km=row.depth_km,
                magnitude=row.magnitude,
                location_description=row.location_description,
                origin=detail.origin,
            )
        )

    store = SqlAlchemyIngestionTransactions(
        create_session_factory(migrated_engine), model_release_verifier=VerifiedReleaseGate()
    )
    assert store.reusable_live_details((row,))[row.source_url] == detail
    assert store.reusable_live_details((replace(row, magnitude=Decimal("5.00")),)) == {}
    assert store.reusable_live_details((replace(row, source_url=row.source_url + "?new"),)) == {}

    with migrated_engine.begin() as connection:
        connection.execute(
            update(earthquake_event_revisions)
            .where(earthquake_event_revisions.c.event_revision_id == revision_id)
            .values(source_time_precision="minute", event_time=row.occurred_at, origin=None)
        )
    assert store.reusable_live_details((row,)) == {}
    assert store.reusable_live_details(()) == {}
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(earthquake_events.c.event_id)) == event_id
