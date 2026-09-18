"""Typed environment-backed worker settings."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_BOOTSTRAP_RUN_MANIFEST = Path("database/initialization/bootstrap-readiness.json")
DEFAULT_BOOTSTRAP_REQUIRED_AVAILABLE_THROUGH = datetime.fromisoformat("2026-09-01T00:00:00+08:00")


class Settings(BaseSettings):
    """Configuration shared by the Phase 1 worker entry points."""

    database_url: str = Field(
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
    )
    redis_url: str = Field(
        validation_alias=AliasChoices("REDIS_URL", "redis_url"),
    )
    phivolcs_catalog_url: str = Field(
        validation_alias=AliasChoices("PHIVOLCS_CATALOG_URL", "phivolcs_catalog_url"),
    )
    model_release_id: UUID = Field(
        validation_alias=AliasChoices("MODEL_RELEASE_ID", "model_release_id"),
    )
    model_artifact_directory: Path = Field(
        default=Path("model-artifacts"),
        validation_alias=AliasChoices("MODEL_ARTIFACT_DIRECTORY", "model_artifact_directory"),
    )
    bootstrap_run_manifest: Path = Field(
        default=DEFAULT_BOOTSTRAP_RUN_MANIFEST,
        validation_alias=AliasChoices(
            "BOOTSTRAP_RUN_MANIFEST",
            "bootstrap_run_manifest",
        ),
    )
    bootstrap_required_available_through: datetime = Field(
        default=DEFAULT_BOOTSTRAP_REQUIRED_AVAILABLE_THROUGH,
        validation_alias=AliasChoices(
            "BOOTSTRAP_REQUIRED_AVAILABLE_THROUGH",
            "bootstrap_required_available_through",
        ),
    )

    poll_interval_seconds: int = Field(
        default=300,
        ge=300,
        le=86_400,
        validation_alias=AliasChoices("POLL_INTERVAL_SECONDS", "poll_interval_seconds"),
    )
    dispatcher_poll_interval_seconds: int = Field(
        default=5,
        ge=1,
        le=300,
        validation_alias=AliasChoices(
            "DISPATCHER_POLL_INTERVAL_SECONDS",
            "dispatcher_poll_interval_seconds",
        ),
    )
    dispatcher_batch_size: int = Field(
        default=10,
        ge=1,
        le=10,
        validation_alias=AliasChoices("DISPATCHER_BATCH_SIZE", "dispatcher_batch_size"),
    )
    dispatch_lease_seconds: int = Field(
        default=60,
        ge=1,
        le=3_600,
        validation_alias=AliasChoices("DISPATCH_LEASE_SECONDS", "dispatch_lease_seconds"),
    )
    ingestor_lease_seconds: int = Field(
        default=900,
        ge=60,
        le=86_400,
        validation_alias=AliasChoices("INGESTOR_LEASE_SECONDS", "ingestor_lease_seconds"),
    )
    ingestor_concurrency: int = Field(
        default=1,
        ge=1,
        le=1,
        validation_alias=AliasChoices("INGESTOR_CONCURRENCY", "ingestor_concurrency"),
    )
    detail_request_delay_seconds: float = Field(
        default=0.1,
        ge=0,
        le=60,
        validation_alias=AliasChoices(
            "DETAIL_REQUEST_DELAY_SECONDS",
            "detail_request_delay_seconds",
        ),
    )
    retry_delays_seconds: tuple[int, int, int] = Field(
        default=(30, 120, 600),
        validation_alias=AliasChoices("RETRY_DELAYS_SECONDS", "retry_delays_seconds"),
    )
    max_response_bytes: int = Field(
        default=2_000_000,
        ge=1_024,
        le=50_000_000,
        validation_alias=AliasChoices("MAX_RESPONSE_BYTES", "max_response_bytes"),
    )
    http_connect_timeout_seconds: float = Field(
        default=10,
        gt=0,
        le=300,
        validation_alias=AliasChoices(
            "HTTP_CONNECT_TIMEOUT_SECONDS",
            "http_connect_timeout_seconds",
        ),
    )
    http_read_timeout_seconds: float = Field(
        default=30,
        gt=0,
        le=600,
        validation_alias=AliasChoices("HTTP_READ_TIMEOUT_SECONDS", "http_read_timeout_seconds"),
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        validation_alias=AliasChoices("LOG_LEVEL", "log_level"),
    )

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        validate_default=True,
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        return _validate_url(
            value,
            allowed_schemes={"postgresql+psycopg"},
            field_name="DATABASE_URL",
            require_path=True,
        )

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        return _validate_url(
            value,
            allowed_schemes={"redis", "rediss"},
            field_name="REDIS_URL",
            require_path=False,
        )

    @field_validator("phivolcs_catalog_url")
    @classmethod
    def validate_phivolcs_catalog_url(cls, value: str) -> str:
        return _validate_url(
            value,
            allowed_schemes={"https"},
            field_name="PHIVOLCS_CATALOG_URL",
            require_path=False,
        )

    @field_validator("retry_delays_seconds")
    @classmethod
    def validate_retry_delays(cls, value: tuple[int, int, int]) -> tuple[int, int, int]:
        if any(delay <= 0 for delay in value):
            raise ValueError("RETRY_DELAYS_SECONDS values must be positive")
        return value

    @field_validator("bootstrap_required_available_through")
    @classmethod
    def validate_bootstrap_cutoff(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("BOOTSTRAP_REQUIRED_AVAILABLE_THROUGH must include a UTC offset")
        return value

    def safe_summary(self) -> dict[str, object]:
        """Return configuration metadata that excludes credentials and full URLs."""

        return {
            "database_scheme": urlsplit(self.database_url).scheme,
            "redis_scheme": urlsplit(self.redis_url).scheme,
            "model_release_configured": True,
            "model_artifact_directory": str(self.model_artifact_directory),
            "bootstrap_run_manifest": str(self.bootstrap_run_manifest),
            "bootstrap_required_available_through": (
                self.bootstrap_required_available_through.isoformat()
            ),
            "poll_interval_seconds": self.poll_interval_seconds,
            "log_level": self.log_level,
        }


def _validate_url(
    value: str,
    *,
    allowed_schemes: set[str],
    field_name: str,
    require_path: bool,
) -> str:
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme not in allowed_schemes or not parsed.hostname:
        schemes = ", ".join(sorted(allowed_schemes))
        raise ValueError(f"{field_name} must use one of: {schemes}")
    if require_path and parsed.path in {"", "/"}:
        raise ValueError(f"{field_name} must include a database name")
    if any(character.isspace() for character in candidate):
        raise ValueError(f"{field_name} must not contain whitespace")
    return candidate
