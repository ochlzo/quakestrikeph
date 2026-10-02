"""Documented account constraints are authoritative even outside HTTP validation."""

from uuid import uuid4

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError

from quakestrike.infrastructure.database.tables import audit_logs, users

pytestmark = pytest.mark.integration


def test_profile_defaults_and_user_audit_foreign_key(migrated_engine):
    user_id = uuid4()
    with migrated_engine.begin() as connection:
        row = (
            connection.execute(
                insert(users)
                .values(
                    user_id=user_id,
                    clerk_user_id=f"user_{user_id}",
                    display_name="Reader",
                    email="reader@example.invalid",
                )
                .returning(users)
            )
            .mappings()
            .one()
        )
        assert not row["email_enabled"] and not row["sms_enabled"]
        assert row["onboarding_completed_at"] is None
        connection.execute(
            insert(audit_logs).values(
                audit_id=uuid4(),
                actor_type="user",
                actor_user_id=user_id,
                action="profile_saved",
                outcome="succeeded",
                correlation_id=uuid4(),
            )
        )
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM users WHERE user_id=:id"), {"id": user_id})


@pytest.mark.parametrize(
    "changes",
    [
        {"email_enabled": True},
        {"sms_enabled": True},
        {"mobile_number": "+639171234567"},
        {"alert_trigger_magnitude": "NaN"},
        {"alert_trigger_magnitude": 10.1},
        {"nearby_alerts_only": True},
        {"alert_location_latitude": 14},
        {"alert_trigger_distance_km": 0},
    ],
)
def test_account_constraints_reject_invalid_enrollment(migrated_engine, changes):
    user_id = uuid4()
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            insert(users).values(
                user_id=user_id,
                clerk_user_id=f"user_{user_id}",
                display_name="Reader",
                email="reader@example.invalid",
                **changes,
            )
        )
