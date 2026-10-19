from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select

from quakestrike.infrastructure.database.tables import audit_logs, users
from quakestrike.operator_accounts import delete_local_accounts, find_local_accounts

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


def test_delete_removes_the_user_and_its_audit_evidence(migrated_engine) -> None:
    with migrated_engine.begin() as connection:
        target_id = _insert_user(connection, "Reader@Example.invalid")
        _insert_user(connection, "other@example.invalid")
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

    with migrated_engine.begin() as connection:
        accounts = find_local_accounts(connection, ("reader@example.invalid",))
        assert [account.user_id for account in accounts] == [target_id]
        counts = delete_local_accounts(connection, [account.user_id for account in accounts])

    assert counts.users == 1
    assert counts.audit_logs == 2
    with migrated_engine.begin() as connection:
        assert connection.scalar(select(func.count()).select_from(users)) == 1
        assert connection.scalar(select(func.count()).select_from(audit_logs)) == 0
