"""Pure PHIVOLCS identity and reconciliation policy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from quakestrike.domain.source_rows import NormalizedSourceRow

MAX_FALLBACK_LATITUDE_DIFFERENCE = Decimal("0.25")
MAX_FALLBACK_LONGITUDE_DIFFERENCE = Decimal("0.25")
MAX_FALLBACK_MAGNITUDE_DIFFERENCE = Decimal("1.0")


class ReconciliationAction(StrEnum):
    """The safe result for one normalized source row."""

    CREATE = "inserted"
    ATTACH = "candidate"
    REJECT = "rejected"


@dataclass(frozen=True, slots=True)
class EventCandidate:
    """Latest observation used to test an existing event for a group fallback."""

    event_id: UUID
    source_event_group_id: str | None
    latitude: Decimal
    longitude: Decimal
    magnitude: Decimal


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """A decision that has no dependency on persistence or transport."""

    action: ReconciliationAction
    event_id: UUID | None = None
    rejection_code: str | None = None


def choose_group_fallback(
    row: NormalizedSourceRow, candidates: tuple[EventCandidate, ...]
) -> ReconciliationResult:
    """Return the one existing event that passes every approved fallback check."""

    if row.source_event_group_id is None:
        return ReconciliationResult(ReconciliationAction.REJECT, rejection_code="MISSING_SOURCE_ID")

    matches = tuple(
        candidate
        for candidate in candidates
        if candidate.source_event_group_id == row.source_event_group_id
        and abs(candidate.latitude - row.latitude) <= MAX_FALLBACK_LATITUDE_DIFFERENCE
        and abs(candidate.longitude - row.longitude) <= MAX_FALLBACK_LONGITUDE_DIFFERENCE
        and abs(candidate.magnitude - row.magnitude) <= MAX_FALLBACK_MAGNITUDE_DIFFERENCE
    )
    if len(matches) == 1:
        return ReconciliationResult(ReconciliationAction.ATTACH, event_id=matches[0].event_id)
    if not matches:
        return ReconciliationResult(
            ReconciliationAction.REJECT, rejection_code="UNMATCHED_FALLBACK"
        )
    return ReconciliationResult(ReconciliationAction.REJECT, rejection_code="AMBIGUOUS_FALLBACK")
