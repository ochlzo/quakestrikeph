from __future__ import annotations

from datetime import datetime
from pathlib import Path

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


def test_example_environment_file_is_valid() -> None:
    settings = Settings(_env_file=REPOSITORY_ROOT / ".env.example")

    assert settings.ingestor_concurrency == 1
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.model_release_id == SEIS_RELEASE_ID


def test_settings_reject_naive_bootstrap_cutoff() -> None:
    values = valid_settings().model_dump()
    values["bootstrap_required_available_through"] = datetime(2026, 9, 1)

    with pytest.raises(ValidationError, match="must include a UTC offset"):
        Settings(_env_file=None, **values)


def test_settings_require_database_and_redis_urls() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
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


@pytest.mark.parametrize(("soft", "hard"), [(360, 360), (361, 360), (300, 900)])
def test_prediction_task_limits_must_fit_inside_processing_lease(soft, hard) -> None:
    values = valid_settings().model_dump()
    values["prediction_soft_time_limit_seconds"] = soft
    values["prediction_hard_time_limit_seconds"] = hard
    with pytest.raises(ValidationError, match="soft < hard < 900-second lease"):
        Settings(_env_file=None, **values)
