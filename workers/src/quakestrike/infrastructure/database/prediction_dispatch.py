"""Compatibility name for the shared durable dispatch store."""

from quakestrike.application.dispatch import DispatchClaimLost
from quakestrike.infrastructure.database.dispatch import SqlAlchemyDispatchStore

SqlAlchemyPredictionDispatchStore = SqlAlchemyDispatchStore

__all__ = ["DispatchClaimLost", "SqlAlchemyPredictionDispatchStore"]
