from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from quakestrike.application.model_releases import ModelReleaseRecord
from quakestrike.infrastructure import startup
from quakestrike.infrastructure.database.engine import create_session_factory
from quakestrike.infrastructure.database.model_releases import SqlAlchemyModelReleaseRegistry
from quakestrike.infrastructure.database.tables import model_releases
from quakestrike.infrastructure.models.release_manifest import VerifiedReleaseManifest
from quakestrike.infrastructure.settings import Settings

pytestmark = pytest.mark.integration


def _release(**changes: object) -> ModelReleaseRecord:
    values: dict[str, object] = {
        "model_release_id": uuid4(),
        "version_label": "SEIS 1.0",
        "artifact_manifest_uri": "seis-1.0/manifest.json",
        "artifact_manifest_hash": "a" * 64,
        "input_schema_version": "input.v1",
        "output_schema_version": "output.v1",
    }
    values.update(changes)
    return ModelReleaseRecord(**values)  # type: ignore[arg-type]


def test_registration_stores_a_verified_release_and_exact_replay_is_a_no_op(
    migrated_engine,
) -> None:
    registry = SqlAlchemyModelReleaseRegistry(create_session_factory(migrated_engine))
    release = _release()

    assert registry.register(release) is True
    assert registry.get(release.model_release_id) == release
    assert registry.register(release) is False
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(model_releases)) == 1


def test_registration_rejects_identity_or_version_conflicts_without_mutating_row(
    migrated_engine,
) -> None:
    registry = SqlAlchemyModelReleaseRegistry(create_session_factory(migrated_engine))
    release = _release()
    registry.register(release)

    with pytest.raises(ValueError, match="conflicts"):
        registry.register(
            _release(model_release_id=release.model_release_id, artifact_manifest_hash="b" * 64)
        )
    with pytest.raises(ValueError, match="conflicts"):
        registry.register(_release(version_label=release.version_label))

    assert registry.get(release.model_release_id) == release


@pytest.mark.parametrize("field", ["model_release_id", "version_label"])
def test_unique_key_collision_preserves_the_original_row(migrated_engine, field: str) -> None:
    registry = SqlAlchemyModelReleaseRegistry(create_session_factory(migrated_engine))
    original = _release()
    assert registry.register(original) is True
    distinct = _release(
        version_label="SEIS 2.0",
        artifact_manifest_uri="seis-2.0/manifest.json",
        artifact_manifest_hash="b" * 64,
        input_schema_version="input.v2",
        output_schema_version="output.v2",
    )
    attempted = replace(distinct, **{field: getattr(original, field)})

    with pytest.raises(ValueError, match="conflicts"):
        registry.register(attempted)

    assert registry.get(original.model_release_id) == original
    if attempted.model_release_id != original.model_release_id:
        assert registry.get(attempted.model_release_id) is None
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(model_releases)) == 1


def test_distinct_releases_can_share_schema_versions_and_manifest_values(migrated_engine) -> None:
    registry = SqlAlchemyModelReleaseRegistry(create_session_factory(migrated_engine))
    first = _release()
    second = _release(version_label="SEIS 2.0")

    assert registry.register(first) is True
    assert registry.register(second) is True
    assert registry.get(first.model_release_id) == first
    assert registry.get(second.model_release_id) == second
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(model_releases)) == 2


def test_concurrent_registration_serializes_exact_replay(migrated_engine) -> None:
    registry = SqlAlchemyModelReleaseRegistry(create_session_factory(migrated_engine))
    release = _release()
    start = Barrier(2)

    def register() -> bool:
        start.wait(timeout=10)
        return registry.register(release)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(register)
        second = pool.submit(register)
        assert sorted((first.result(timeout=15), second.result(timeout=15))) == [False, True]
    assert registry.get(release.model_release_id) == release
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(model_releases)) == 1


def test_concurrent_partial_collision_has_one_winner_and_no_partial_row(
    migrated_engine,
) -> None:
    registry = SqlAlchemyModelReleaseRegistry(create_session_factory(migrated_engine))
    first_release = _release()
    second_release = _release(
        artifact_manifest_uri="seis-other/manifest.json",
        artifact_manifest_hash="b" * 64,
        input_schema_version="input.v2",
        output_schema_version="output.v2",
    )
    start = Barrier(2)

    def register(release: ModelReleaseRecord) -> bool | str:
        start.wait(timeout=10)
        try:
            return registry.register(release)
        except ValueError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(register, first_release)
        two = pool.submit(register, second_release)
        assert sorted((str(one.result(timeout=15)), str(two.result(timeout=15)))) == [
            "True",
            "conflict",
        ]
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(model_releases)) == 1
    assert (registry.get(first_release.model_release_id) is None) != (
        registry.get(second_release.model_release_id) is None
    )


def test_startup_check_does_not_register_an_absent_release(migrated_engine, monkeypatch) -> None:
    release = _release()
    verified = VerifiedReleaseManifest(
        release.model_release_id,
        release.version_label,
        release.input_schema_version,
        release.output_schema_version,
        release.artifact_manifest_uri,
        release.artifact_manifest_hash,
        (),
    )
    settings = Settings(
        _env_file=None,
        database_url=migrated_engine.url.render_as_string(hide_password=False),
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/catalog",
        model_release_id=release.model_release_id,
    )
    monkeypatch.setattr(startup, "load_verified_release_manifest", lambda *_, **__: verified)

    result = startup.ModelReleaseStartupGate(settings).check()

    assert result.ready is False
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(model_releases)) == 0
