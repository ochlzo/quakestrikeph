"""Synchronous SQLAlchemy engine and session factories."""

from collections.abc import Callable

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

SessionFactory = Callable[[], Session]


def create_database_engine(database_url: str, *, statement_timeout_ms: int | None = None) -> Engine:
    """Create an engine when a process starts, never during module import."""

    connect_args = {}
    if statement_timeout_ms is not None:
        if not 1 <= statement_timeout_ms <= 60000:
            raise ValueError("Database statement timeout must be bounded.")
        connect_args = {
            "connect_timeout": 5,
            "options": f"-c statement_timeout={statement_timeout_ms} -c lock_timeout=1000",
        }
    return create_engine(
        database_url, pool_pre_ping=True, hide_parameters=True, connect_args=connect_args
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return sessions whose transaction boundaries are controlled by callers."""

    return sessionmaker(bind=engine, expire_on_commit=False)
