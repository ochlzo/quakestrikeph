"""PostgreSQL adapter for immutable model-release registration."""

from __future__ import annotations

from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError

from quakestrike.application.model_releases import ModelReleaseRecord
from quakestrike.infrastructure.database.engine import SessionFactory
from quakestrike.infrastructure.database.tables import model_releases


class SqlAlchemyModelReleaseRegistry:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def get(self, release_id):
        with self._session_factory() as session:
            row = (
                session.execute(
                    select(model_releases).where(model_releases.c.model_release_id == release_id)
                )
                .mappings()
                .one_or_none()
            )
        return _record(row) if row else None

    def register(self, release: ModelReleaseRecord) -> bool:
        with self._session_factory() as session:
            try:
                with session.begin():
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(:key)"), {"key": 714_299_031}
                    )
                    existing = [
                        _record(row)
                        for row in session.execute(
                            select(model_releases).where(
                                (model_releases.c.model_release_id == release.model_release_id)
                                | (model_releases.c.version_label == release.version_label)
                            )
                        ).mappings()
                    ]
                    if release in existing:
                        return False
                    if any(_shares_immutable_identity(row, release) for row in existing):
                        raise ValueError(
                            "An immutable model release conflicts with the requested registration."
                        )
                    session.execute(insert(model_releases).values(**_values(release)))
                return True
            except IntegrityError as error:
                session.rollback()
                existing = self.get(release.model_release_id)
                if existing == release:
                    return False
                raise ValueError(
                    "An immutable model release conflicts with the requested registration."
                ) from error


def _shares_immutable_identity(existing: ModelReleaseRecord, requested: ModelReleaseRecord) -> bool:
    return (
        existing.model_release_id == requested.model_release_id
        or existing.version_label == requested.version_label
    )


def _values(release: ModelReleaseRecord) -> dict[str, object]:
    return {
        "model_release_id": release.model_release_id,
        "version_label": release.version_label,
        "artifact_manifest_uri": release.artifact_manifest_uri,
        "artifact_manifest_hash": release.artifact_manifest_hash,
        "input_schema_version": release.input_schema_version,
        "output_schema_version": release.output_schema_version,
    }


def _record(row) -> ModelReleaseRecord:
    return ModelReleaseRecord(
        model_release_id=row["model_release_id"],
        version_label=row["version_label"],
        artifact_manifest_uri=row["artifact_manifest_uri"],
        artifact_manifest_hash=row["artifact_manifest_hash"],
        input_schema_version=row["input_schema_version"],
        output_schema_version=row["output_schema_version"],
    )
