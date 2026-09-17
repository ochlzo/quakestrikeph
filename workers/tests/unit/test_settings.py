from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from quakestrike.infrastructure.models.packaging import SEIS_RELEASE_ID
from quakestrike.infrastructure.settings import Settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def valid_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        redis_url="redis://redis:6379/0",
        phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
        model_release_id="00000000-0000-0000-0000-000000000001",
    )


def test_settings_validate_required_values_and_operational_defaults() -> None:
    settings = valid_settings()

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.model_release_id == UUID("00000000-0000-0000-0000-000000000001")
    assert settings.poll_interval_seconds == 300
    assert settings.dispatcher_batch_size == 10
    assert settings.ingestor_concurrency == 1
    assert settings.retry_delays_seconds == (30, 120, 600)


def test_example_environment_file_is_valid() -> None:
    settings = Settings(_env_file=REPOSITORY_ROOT / ".env.example")

    assert settings.ingestor_concurrency == 1
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.model_release_id == SEIS_RELEASE_ID


def test_settings_require_database_and_redis_urls() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
            model_release_id="00000000-0000-0000-0000-000000000001",
        )


def test_settings_reject_plain_postgresql_scheme_without_psycopg_driver() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(
            _env_file=None,
            database_url="postgresql://worker:secret@postgres:5432/quakestrike",
            redis_url="redis://redis:6379/0",
            phivolcs_catalog_url="https://example.invalid/phivolcs/catalog",
            model_release_id="00000000-0000-0000-0000-000000000001",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "https://not-postgres.example/database"),
        ("redis_url", "https://not-redis.example/queue"),
        ("phivolcs_catalog_url", "http://insecure.example/catalog"),
        ("poll_interval_seconds", 299),
        ("ingestor_concurrency", 2),
    ],
)
def test_settings_reject_invalid_values(field: str, value: object) -> None:
    values: dict[str, object] = {
        "_env_file": None,
        "database_url": "postgresql+psycopg://worker:secret@postgres:5432/quakestrike",
        "redis_url": "redis://redis:6379/0",
        "phivolcs_catalog_url": "https://example.invalid/phivolcs/catalog",
        "model_release_id": "00000000-0000-0000-0000-000000000001",
    }
    values[field] = value

    with pytest.raises(ValidationError):
        Settings(**values)
