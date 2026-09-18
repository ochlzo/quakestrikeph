"""Compatibility name for the shared durable dispatch store."""

from quakestrike.infrastructure.database.dispatch import (
    DISPATCH_ATTEMPTS_EXHAUSTED,
    DISPATCH_EXHAUSTED_ERROR_CODE,
    DISPATCH_INVALID_ERROR_CODE,
    DISPATCH_TARGET_TERMINAL,
    SqlAlchemyDispatchStore,
)

SqlAlchemyIngestionDispatchStore = SqlAlchemyDispatchStore

__all__ = [
    "DISPATCH_ATTEMPTS_EXHAUSTED",
    "DISPATCH_EXHAUSTED_ERROR_CODE",
    "DISPATCH_INVALID_ERROR_CODE",
    "DISPATCH_TARGET_TERMINAL",
    "SqlAlchemyIngestionDispatchStore",
]
