"""Synchronous SQLAlchemy engine and session factories."""

from collections.abc import Callable

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

SessionFactory = Callable[[], Session]


def create_database_engine(database_url: str) -> Engine:
    """Create an engine when a process starts, never during module import."""

    return create_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return sessions whose transaction boundaries are controlled by callers."""

    return sessionmaker(bind=engine, expire_on_commit=False)
