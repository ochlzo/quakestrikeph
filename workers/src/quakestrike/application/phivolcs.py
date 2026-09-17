"""Application boundary for current PHIVOLCS catalog retrieval."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from quakestrike.domain.source_rows import CatalogParseResult


class CatalogRetrievalError(RuntimeError):
    """A sanitized catalog-level retrieval failure exposed by an adapter."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class CatalogRetrievalLeaseLost(RuntimeError):
    """The caller's processing lease ended while retrieval was in progress."""


class CurrentCatalogRetriever(Protocol):
    """Retrieves a normalized and detail-enriched current catalog response."""

    def retrieve_current_catalog(
        self, *, heartbeat: Callable[[], bool] | None = None
    ) -> CatalogParseResult:
        """Return one current catalog response without reconciliation or persistence."""
