"""PostgreSQL locking, evidence reads, and audit writes for bootstrap recovery."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from quakestrike.application.bootstrap_recovery import BootstrapRecoveryAudit
from quakestrike.application.features import HistorySelection
from quakestrike.application.persistence import IngestionRunState
from quakestrike.domain.features import HistoryCoverage
from quakestrike.infrastructure.database.engine import SessionFactory
from quakestrike.infrastructure.database.feature_history import SqlAlchemyFeatureHistoryQuery
from quakestrike.infrastructure.database.repositories import (
    SqlAlchemyIngestionTransactions,
    _ingestion_run_state,
)
from quakestrike.infrastructure.database.tables import audit_logs, ingestion_runs

_RETENTION_LOCK = 5_173_835_459


class SqlAlchemyBootstrapRecovery:
    def __init__(self, session_factory: SessionFactory):
        self._session_factory = session_factory

    @contextmanager
    def transaction(self) -> Iterator[SqlAlchemyBootstrapRecoveryTransaction]:
        with self._session_factory() as session, session.begin():
            # Serialize recovery verification with checkpoint retention.
            session.execute(select(func.pg_advisory_xact_lock(_RETENTION_LOCK)))
            yield SqlAlchemyBootstrapRecoveryTransaction(session)


class SqlAlchemyBootstrapRecoveryTransaction:
    def __init__(self, session: Session):
        self._session = session

    def completed_runs(self, run_id: UUID | None) -> tuple[IngestionRunState, ...]:
        statement = select(ingestion_runs).where(
            ingestion_runs.c.trigger_type == "backfill", ingestion_runs.c.status == "succeeded"
        )
        if run_id is not None:
            statement = statement.where(ingestion_runs.c.run_id == run_id)
        rows = self._session.execute(statement.with_for_update()).mappings().all()
        checked_at = self._session.scalar(select(func.now()))
        return tuple(
            replace(_ingestion_run_state(row), retention_checked_at=checked_at) for row in rows
        )

    def database_counts(self, run_id: UUID) -> Mapping[str, int]:
        return SqlAlchemyIngestionTransactions.bootstrap_database_counts_in_session(
            self._session, run_id
        )

    def history(self, anchor: datetime, coverage: HistoryCoverage) -> HistorySelection:
        return SqlAlchemyFeatureHistoryQuery.select_history_at_in_session(
            self._session, anchor, coverage=coverage
        )

    def audit(self, audit_id: UUID) -> BootstrapRecoveryAudit | None:
        row = (
            self._session.execute(select(audit_logs).where(audit_logs.c.audit_id == audit_id))
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return BootstrapRecoveryAudit(
            audit_id=row["audit_id"],
            action=row["action"],
            target_id=row["target_id"],
            outcome=row["outcome"],
            correlation_id=row["correlation_id"],
            metadata=row["metadata"],
        )

    def record_audit(self, audit: BootstrapRecoveryAudit) -> None:
        self._session.execute(
            insert(audit_logs).values(
                audit_id=audit.audit_id,
                actor_type="system",
                actor_service="operator-cli",
                action=audit.action,
                target_type="ingestion_run",
                target_id=audit.target_id,
                outcome=audit.outcome,
                correlation_id=audit.correlation_id,
                metadata=dict(audit.metadata),
            )
        )
