from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select

from quakestrike.infrastructure.database.tables import (
    alert_delivery_attempts,
    alert_recipients,
    audit_logs,
    users,
)
from quakestrike.operator_accounts import (
    AccountCleanupError,
    _delete_database,
    build_preview,
    delete_local_accounts,
    find_local_accounts,
)

from .test_forecast_alert_evidence import completed_alert
from .test_prediction_worker import NOW

pytestmark = pytest.mark.integration


def _insert_user(connection, email: str) -> UUID:
    user_id = uuid4()
    connection.execute(
        insert(users).values(
            user_id=user_id,
            clerk_user_id=f"user_{user_id}",
            display_name="Reader",
            email=email,
        )
    )
    return user_id


def test_delete_removes_only_the_selected_users_and_their_evidence(migrated_engine) -> None:
    alert_id = completed_alert(migrated_engine)
    with migrated_engine.begin() as connection:
        target_id = _insert_user(connection, "Reader@Example.invalid")
        other_id = _insert_user(connection, "other@example.invalid")
        for user_id in (target_id, other_id):
            recipient_id = uuid4()
            connection.execute(
                insert(alert_recipients).values(
                    recipient_id=recipient_id,
                    alert_job_id=alert_id,
                    user_id=user_id,
                    channel="email",
                    destination_snapshot=f"{user_id}@example.invalid",
                    eligibility_snapshot={},
                    delivery_idempotency_key=str(recipient_id),
                    status="sending",
                    processing_lease_expires_at=NOW + timedelta(minutes=1),
                    worker_execution_id=uuid4(),
                )
            )
            connection.execute(
                insert(alert_delivery_attempts).values(
                    delivery_attempt_id=uuid4(),
                    recipient_id=recipient_id,
                    attempt_number=1,
                    provider="brevo",
                    correlation_id=uuid4(),
                    content_variant="general",
                    eligibility_snapshot={},
                )
            )
        connection.execute(
            insert(audit_logs).values(
                audit_id=uuid4(),
                actor_type="user",
                actor_user_id=target_id,
                action="profile_saved",
                outcome="succeeded",
                correlation_id=uuid4(),
            )
        )
        connection.execute(
            insert(audit_logs).values(
                audit_id=uuid4(),
                actor_type="system",
                actor_service="backend",
                action="account_read",
                target_type="user",
                target_id=str(target_id),
                outcome="succeeded",
                correlation_id=uuid4(),
            )
        )
        audit_count = connection.scalar(select(func.count()).select_from(audit_logs))

    with migrated_engine.begin() as connection:
        accounts = find_local_accounts(connection, ("reader@example.invalid",))
        assert [account.user_id for account in accounts] == [target_id]
        counts = delete_local_accounts(connection, [account.user_id for account in accounts])

    assert counts.users == 1
    assert counts.audit_logs == 2
    assert counts.alert_recipients == 1
    assert counts.alert_delivery_attempts == 1
    with migrated_engine.begin() as connection:
        assert connection.scalar(select(func.count()).select_from(users)) == 1
        assert connection.scalar(select(func.count()).select_from(audit_logs)) == audit_count - 2
        assert connection.execute(select(alert_recipients.c.user_id)).scalars().all() == [other_id]
        assert connection.scalar(select(func.count()).select_from(alert_delivery_attempts)) == 1


@pytest.mark.parametrize("change", [None, "accounts", "evidence"])
def test_confirmed_selection_is_rechecked_inside_the_transaction(migrated_engine, change) -> None:
    email = "reader@example.invalid"
    with migrated_engine.begin() as connection:
        target_id = _insert_user(connection, email)
        preview = build_preview(connection, (email,), SimpleNamespace(find_by_email=lambda _: ()))

    if change is not None:
        with migrated_engine.begin() as connection:
            if change == "accounts":
                _insert_user(connection, email)
            else:
                connection.execute(
                    insert(audit_logs).values(
                        audit_id=uuid4(),
                        actor_type="user",
                        actor_user_id=target_id,
                        action="profile_saved",
                        outcome="succeeded",
                        correlation_id=uuid4(),
                    )
                )
        with pytest.raises(AccountCleanupError, match="plan_changed"):
            _delete_database(migrated_engine, (email,), expected=preview)
        with migrated_engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(users)) == (
                2 if change == "accounts" else 1
            )
            assert connection.scalar(select(func.count()).select_from(audit_logs)) == (
                1 if change == "evidence" else 0
            )
    else:
        accounts, counts = _delete_database(migrated_engine, (email,), expected=preview)
        assert accounts == preview.accounts
        assert counts.users == 1
        with migrated_engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(users)) == 0
