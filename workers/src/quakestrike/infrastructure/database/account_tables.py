"""Backend-owned Bulletin account metadata; workers do not mutate accounts."""

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Numeric, Table, Text, func
from sqlalchemy.dialects.postgresql import ENUM, UUID

from quakestrike.infrastructure.database.metadata import metadata

account_status = ENUM("active", "suspended", "closed", name="account_status", create_type=False)

users = Table(
    "users",
    metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("clerk_user_id", Text, nullable=False, unique=True),
    Column("display_name", Text, nullable=False),
    Column("email", Text, nullable=False),
    Column("email_verified_at", DateTime(timezone=True)),
    Column("email_enabled", Boolean, nullable=False, server_default="false"),
    Column("mobile_number", Text, unique=True),
    Column("mobile_verified_at", DateTime(timezone=True)),
    Column("sms_enabled", Boolean, nullable=False, server_default="false"),
    Column("alert_trigger_magnitude", Numeric(3, 1), nullable=False, server_default="4.5"),
    Column("nearby_alerts_only", Boolean, nullable=False, server_default="false"),
    Column("alert_location_latitude", Numeric(9, 6)),
    Column("alert_location_longitude", Numeric(10, 6)),
    Column("alert_trigger_distance_km", Numeric(10, 3)),
    Column("account_status", account_status, nullable=False, server_default="active"),
    Column("onboarding_completed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "clerk_user_id = btrim(clerk_user_id) AND clerk_user_id <> '' "
        "AND display_name = btrim(display_name) AND length(display_name) BETWEEN 1 AND 100 "
        "AND email = btrim(email) AND email <> ''",
        name="ck_users_names",
    ),
    CheckConstraint(
        "(mobile_number IS NULL) = (mobile_verified_at IS NULL) "
        "AND (mobile_number IS NULL OR mobile_number ~ '^\\+639[0-9]{9}$')",
        name="ck_users_phone",
    ),
    CheckConstraint("alert_trigger_magnitude BETWEEN 1 AND 10", name="ck_users_magnitude"),
    CheckConstraint(
        "(alert_location_latitude IS NULL) = (alert_location_longitude IS NULL) "
        "AND (alert_location_latitude IS NULL OR alert_location_latitude BETWEEN -90 AND 90) "
        "AND (alert_location_longitude IS NULL OR alert_location_longitude BETWEEN -180 AND 180) "
        "AND (alert_trigger_distance_km IS NULL OR alert_trigger_distance_km BETWEEN 1 AND 1000)",
        name="ck_users_location",
    ),
    CheckConstraint(
        "NOT nearby_alerts_only OR (alert_location_latitude IS NOT NULL "
        "AND alert_location_longitude IS NOT NULL AND alert_trigger_distance_km IS NOT NULL)",
        name="ck_users_nearby",
    ),
    CheckConstraint(
        "onboarding_completed_at IS NOT NULL OR (NOT email_enabled AND NOT sms_enabled)",
        name="ck_users_onboarding",
    ),
    CheckConstraint(
        "(NOT sms_enabled OR mobile_verified_at IS NOT NULL) "
        "AND (NOT email_enabled OR email_verified_at IS NOT NULL)",
        name="ck_users_destinations",
    ),
    CheckConstraint(
        "account_status <> 'closed' OR (NOT email_enabled AND NOT sms_enabled "
        "AND mobile_number IS NULL AND mobile_verified_at IS NULL)",
        name="ck_users_closed",
    ),
)
