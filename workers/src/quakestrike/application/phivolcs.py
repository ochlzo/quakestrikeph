"""Application boundary for current PHIVOLCS catalog retrieval."""

from __future__ import annotations

from typing import Protocol

from quakestrike.domain.source_rows import CatalogParseResult


class CurrentCatalogRetriever(Protocol):
    """Retrieves a normalized and detail-enriched current catalog response."""

    def retrieve_current_catalog(self) -> CatalogParseResult:
        """Return one current catalog response without reconciliation or persistence."""
