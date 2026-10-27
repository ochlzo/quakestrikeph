from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from quakestrike.application.reconciliation import (
    coalesce_catalog_rows,
    normalized_input_key,
)
from quakestrike.domain.reconciliation import (
    EventCandidate,
    ReconciliationAction,
    choose_group_fallback,
)
from quakestrike.domain.source_rows import CatalogParseResult, NormalizedSourceRow


def _row(*, bulletin: str | None = "2025_0102_0304_B1", group: str | None = "2025_0102_0304"):
    return NormalizedSourceRow.from_catalog_values(
        occurred_at=datetime(2025, 1, 2, 11, 4, tzinfo=ZoneInfo("Asia/Manila")),
        latitude="10",
        longitude="125",
        depth_km="7",
        magnitude="4.2",
        location_description="Test location",
        source_bulletin_id=bulletin,
        source_event_group_id=group,
        source_url="https://earthquake.phivolcs.dost.gov.ph/bulletin.html",
    )


def _candidate(*, latitude: str = "10", longitude: str = "125", magnitude: str = "4.2"):
    return EventCandidate(
        event_id=UUID("00000000-0000-0000-0000-000000000001"),
        source_event_group_id="2025_0102_0304",
        latitude=Decimal(latitude),
        longitude=Decimal(longitude),
        magnitude=Decimal(magnitude),
    )


@pytest.mark.parametrize(
    "candidate",
    [
        _candidate(latitude="10.250001"),
        _candidate(longitude="123.999999"),
        _candidate(magnitude="5.200001"),
    ],
)
def test_group_fallback_rejects_a_candidate_outside_any_limit(candidate: EventCandidate) -> None:
    result = choose_group_fallback(_row(), (candidate,))

    assert result.action is ReconciliationAction.REJECT
    assert result.rejection_code == "UNMATCHED_FALLBACK"


def test_identical_duplicate_bulletins_coalesce_without_diagnostic_noise() -> None:
    row = _row()
    result = coalesce_catalog_rows(CatalogParseResult((row, row), ()))

    assert result == (row,)
    assert normalized_input_key(row).startswith("row:")
    enriched = row.with_detail_enrichment(
        detail_occurred_at=row.occurred_at.replace(second=37),
        origin="TECTONIC",
        diagnostics=(),
    )
    assert normalized_input_key(row) == normalized_input_key(enriched)
