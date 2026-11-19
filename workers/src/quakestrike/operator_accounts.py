"""Explicit operator cleanup for disposable Bulletin test accounts.

This is not an account-removal product route. The database design retains audit
and delivery evidence for real accounts, so this command deletes that evidence
explicitly using a privileged database login. VPS use requires the separately
approved preview and confirmation procedure in docs/operations/account-cleanup.md.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

import redis
import requests
from pydantic import ValidationError
from redis import Redis
from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.engine import Connection, Engine

from quakestrike.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from quakestrike.infrastructure.database.migration_state import AlembicMigrationStateGate
from quakestrike.infrastructure.database.tables import (
    alert_delivery_attempts,
    alert_recipients,
    audit_logs,
    users,
)
from quakestrike.infrastructure.settings import Settings
from quakestrike.operator_output import print_json

ACTION = "delete-accounts"
MAX_EMAILS = 100

DEFAULT_EMAILS = (
    "johnthetester1@proton.me",
    "johnbenedictkandelarya@gmail.com",
    "jbbc2023-4132-17459@bicol-u.edu.ph",
    "cholocandelaria123@gmail.com",
    "cholocandelaria@proton.me",
)

CLERK_API_URL = "https://api.clerk.com/v1"
PHONE_KEY_SUFFIXES = ("", ":lock", ":cooldown", ":hour", ":day")
REDIS_DELETE_BATCH = 500


class EmailInputError(ValueError):
    """The --emails value cannot be used without guessing."""


class AccountCleanupError(RuntimeError):
    """A preflight refusal that must stop the command before any mutation."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class LocalAccount:
    user_id: UUID
    clerk_user_id: str
    email: str
    mobile_number: str | None


@dataclass(frozen=True, slots=True)
class ClerkAccount:
    clerk_user_id: str
    email: str


@dataclass(frozen=True, slots=True)
class DeletionCounts:
    audit_logs: int = 0
    alert_recipients: int = 0
    alert_delivery_attempts: int = 0
    users: int = 0


@dataclass(frozen=True, slots=True)
class CleanupPreview:
    emails: tuple[str, ...]
    accounts: tuple[LocalAccount, ...]
    clerk_accounts: tuple[ClerkAccount, ...]
    missing_emails: tuple[str, ...]
    audit_logs: int = 0
    alert_recipients: int = 0
    alert_delivery_attempts: int = 0


class ClerkDirectory(Protocol):
    def find_by_email(self, emails: Sequence[str]) -> tuple[ClerkAccount, ...]: ...

    def delete(self, clerk_user_id: str) -> bool: ...


def _matched_email(payload: dict[str, Any], requested: set[str]) -> str | None:
    addresses = payload.get("email_addresses") or []
    for address in addresses:
        candidate = str(address.get("email_address", "")).casefold()
        if candidate in requested:
            return candidate
    return None


class HttpClerkDirectory:
    """Small Clerk Backend API client for the two calls this command needs."""

    def __init__(
        self,
        secret_key: str,
        *,
        session: requests.Session | None = None,
        api_url: str = CLERK_API_URL,
        timeout: float = 15.0,
    ) -> None:
        self._session = session or requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {secret_key}", "Accept": "application/json"}
        )
        self._api_url = api_url.rstrip("/")
        self._timeout = timeout

    def find_by_email(self, emails: Sequence[str]) -> tuple[ClerkAccount, ...]:
        response = self._session.get(
            f"{self._api_url}/users",
            params={"email_address": list(emails), "limit": MAX_EMAILS},
            timeout=self._timeout,
        )
        response.raise_for_status()
        requested = set(emails)
        found: dict[str, ClerkAccount] = {}
        for payload in response.json():
            address = _matched_email(payload, requested)
            if address is None:
                continue
            clerk_user_id = str(payload["id"])
            found[clerk_user_id] = ClerkAccount(clerk_user_id, address)
        return tuple(found.values())

    def delete(self, clerk_user_id: str) -> bool:
        response = self._session.delete(
            f"{self._api_url}/users/{clerk_user_id}", timeout=self._timeout
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True


def parse_emails(raw: str | None) -> tuple[str, ...]:
    """Return the default or caller-supplied addresses, case-folded and unique."""

    if raw is None:
        return DEFAULT_EMAILS
    if not raw.strip():
        raise EmailInputError("The --emails value is empty.")
    addresses: dict[str, None] = {}
    for item in raw.split(","):
        candidate = item.strip()
        if not candidate:
            raise EmailInputError("The --emails value contains an empty item.")
        if any(character.isspace() for character in candidate):
            raise EmailInputError("Separate addresses with commas, not spaces.")
        if "@" not in candidate:
            raise EmailInputError(f"Not an email address: {candidate}")
        addresses.setdefault(candidate.casefold(), None)
    if len(addresses) > MAX_EMAILS:
        raise EmailInputError(f"At most {MAX_EMAILS} addresses are allowed.")
    return tuple(addresses)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def phone_keys(accounts: Iterable[LocalAccount]) -> tuple[str, ...]:
    keys: list[str] = []
    for account in accounts:
        user_prefix = f"bulletin:phone:user:{_digest(account.clerk_user_id)}"
        keys.extend(f"{user_prefix}{suffix}" for suffix in PHONE_KEY_SUFFIXES)
        if account.mobile_number is not None:
            owner_prefix = f"bulletin:phone:owner:{_digest(account.mobile_number)}"
            keys.extend(f"{owner_prefix}{suffix}" for suffix in PHONE_KEY_SUFFIXES)
    return tuple(keys)


def find_local_accounts(
    connection: Connection,
    emails: Sequence[str],
    *,
    lock: bool = False,
) -> tuple[LocalAccount, ...]:
    statement = (
        select(users.c.user_id, users.c.clerk_user_id, users.c.email, users.c.mobile_number)
        .where(func.lower(users.c.email).in_(tuple(emails)))
        .order_by(func.lower(users.c.email), users.c.user_id)
    )
    if lock:
        statement = statement.with_for_update()
    rows = connection.execute(statement)
    return tuple(LocalAccount(*row) for row in rows)


def _delete_statement_for_audits(user_ids: Sequence[UUID]) -> Any:
    targets = [str(user_id) for user_id in user_ids]
    return delete(audit_logs).where(
        or_(
            audit_logs.c.actor_user_id.in_(tuple(user_ids)),
            and_(audit_logs.c.target_type == "user", audit_logs.c.target_id.in_(targets)),
        )
    )


def count_dependents(connection: Connection, user_ids: Sequence[UUID]) -> tuple[int, int, int]:
    if not user_ids:
        return 0, 0, 0
    recipients = select(alert_recipients.c.recipient_id).where(
        alert_recipients.c.user_id.in_(tuple(user_ids))
    )
    audits = connection.scalar(
        select(func.count())
        .select_from(audit_logs)
        .where(
            or_(
                audit_logs.c.actor_user_id.in_(tuple(user_ids)),
                and_(
                    audit_logs.c.target_type == "user",
                    audit_logs.c.target_id.in_([str(user_id) for user_id in user_ids]),
                ),
            )
        )
    )
    recipient_rows = connection.scalar(
        select(func.count())
        .select_from(alert_recipients)
        .where(alert_recipients.c.user_id.in_(tuple(user_ids)))
    )
    attempts = connection.scalar(
        select(func.count())
        .select_from(alert_delivery_attempts)
        .where(alert_delivery_attempts.c.recipient_id.in_(recipients))
    )
    return int(audits or 0), int(recipient_rows or 0), int(attempts or 0)


def delete_local_accounts(connection: Connection, user_ids: Sequence[UUID]) -> DeletionCounts:
    """Delete one user batch and the evidence rows that block it.

    The caller owns the transaction. Children go first so the ``SET NULL``
    update on ``alert_recipients`` never runs.
    """

    if not user_ids:
        return DeletionCounts()
    recipients = select(alert_recipients.c.recipient_id).where(
        alert_recipients.c.user_id.in_(tuple(user_ids))
    )
    attempts = connection.execute(
        delete(alert_delivery_attempts).where(
            alert_delivery_attempts.c.recipient_id.in_(recipients)
        )
    )
    recipient_rows = connection.execute(
        delete(alert_recipients).where(alert_recipients.c.user_id.in_(tuple(user_ids)))
    )
    audits = connection.execute(_delete_statement_for_audits(user_ids))
    deleted_users = connection.execute(delete(users).where(users.c.user_id.in_(tuple(user_ids))))
    return DeletionCounts(
        audit_logs=int(audits.rowcount or 0),
        alert_recipients=int(recipient_rows.rowcount or 0),
        alert_delivery_attempts=int(attempts.rowcount or 0),
        users=int(deleted_users.rowcount or 0),
    )


def build_preview(
    connection: Connection,
    emails: Sequence[str],
    directory: ClerkDirectory,
) -> CleanupPreview:
    accounts = find_local_accounts(connection, emails)
    clerk_accounts = directory.find_by_email(emails)
    matched = {account.email.casefold() for account in accounts}
    matched.update(account.email for account in clerk_accounts)
    missing = tuple(email for email in emails if email not in matched)
    audits, recipients, attempts = count_dependents(connection, [a.user_id for a in accounts])
    return CleanupPreview(
        emails=tuple(emails),
        accounts=accounts,
        clerk_accounts=clerk_accounts,
        missing_emails=missing,
        audit_logs=audits,
        alert_recipients=recipients,
        alert_delivery_attempts=attempts,
    )


def _prepare(settings: Settings) -> tuple[Engine, Redis, HttpClerkDirectory]:
    gate = AlembicMigrationStateGate(settings).check()
    if not gate.ready:
        raise AccountCleanupError("migration_state_not_current")
    secret = settings.clerk_secret_key
    if secret is None or not secret.get_secret_value().strip():
        raise AccountCleanupError("missing_clerk_secret_key")
    if settings.account_redis_url is None:
        raise AccountCleanupError("missing_account_redis_url")
    engine = create_database_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            permitted = connection.scalar(
                text("SELECT has_table_privilege(current_user, 'users', 'DELETE')")
            )
    except Exception as error:
        engine.dispose()
        raise AccountCleanupError("database_unavailable") from error
    if not permitted:
        engine.dispose()
        raise AccountCleanupError("database_role_lacks_delete")
    try:
        client = Redis.from_url(
            settings.account_redis_url,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        client.ping()
    except redis.RedisError as error:
        engine.dispose()
        raise AccountCleanupError("redis_unavailable") from error
    directory = HttpClerkDirectory(settings.clerk_secret_key.get_secret_value())
    return engine, client, directory


def _delete_database(
    engine: Engine, emails: Sequence[str], *, expected: CleanupPreview | None = None
) -> tuple[tuple[LocalAccount, ...], DeletionCounts]:
    factory = create_session_factory(engine)
    with factory() as session, session.begin():
        accounts = find_local_accounts(session.connection(), emails, lock=True)
        if expected is not None:
            counts = count_dependents(session.connection(), [a.user_id for a in accounts])
            if accounts != expected.accounts or counts != (
                expected.audit_logs,
                expected.alert_recipients,
                expected.alert_delivery_attempts,
            ):
                raise AccountCleanupError("plan_changed")
        counts = delete_local_accounts(session.connection(), [a.user_id for a in accounts])
    return accounts, counts


def _delete_clerk(
    directory: ClerkDirectory, accounts: Iterable[ClerkAccount]
) -> tuple[int, tuple[ClerkAccount, ...]]:
    deleted = 0
    failed: list[ClerkAccount] = []
    for account in accounts:
        try:
            if directory.delete(account.clerk_user_id):
                deleted += 1
        except Exception:
            failed.append(account)
    return deleted, tuple(failed)


def _delete_redis(client: Redis, accounts: Sequence[LocalAccount]) -> int:
    keys = list(phone_keys(accounts))
    for account in accounts:
        user_key = f"bulletin:phone:user:{_digest(account.clerk_user_id)}"
        pending = client.get(user_key)
        if pending is not None:
            owner_prefix = f"bulletin:phone:owner:{_digest(json.loads(pending)['phone'])}"
            keys.extend(f"{owner_prefix}{suffix}" for suffix in PHONE_KEY_SUFFIXES)
    keys = list(dict.fromkeys(keys))
    deleted = 0
    for start in range(0, len(keys), REDIS_DELETE_BATCH):
        chunk = keys[start : start + REDIS_DELETE_BATCH]
        deleted += int(client.delete(*chunk) or 0)
    return deleted


def _plan_lines(preview: CleanupPreview) -> None:
    print(f"plan: {len(preview.emails)} emails")
    for account in preview.accounts:
        print(
            f"  local  {account.email}  user_id={account.user_id}  "
            f"clerk_user_id={account.clerk_user_id}"
        )
    for account in preview.clerk_accounts:
        print(f"  clerk  {account.email}  clerk_user_id={account.clerk_user_id}")
    for email in preview.missing_emails:
        print(f"  missing  {email}")


def _payload(
    status: str,
    preview: CleanupPreview,
    *,
    counts: DeletionCounts | None = None,
    clerk_deleted: int = 0,
    clerk_failed: Sequence[ClerkAccount] = (),
    redis_deleted: int = 0,
) -> dict[str, Any]:
    effective = counts or DeletionCounts(
        audit_logs=preview.audit_logs,
        alert_recipients=preview.alert_recipients,
        alert_delivery_attempts=preview.alert_delivery_attempts,
        users=len(preview.accounts),
    )
    return {
        "action": ACTION,
        "status": status,
        "emails": list(preview.emails),
        "missing_emails": list(preview.missing_emails),
        "local_accounts": len(preview.accounts),
        "clerk_users": len(preview.clerk_accounts),
        "clerk_users_deleted": clerk_deleted,
        "clerk_users_failed": [
            {"clerk_user_id": account.clerk_user_id, "email": account.email}
            for account in clerk_failed
        ],
        "redis_keys_deleted": redis_deleted,
        "audit_logs": effective.audit_logs,
        "alert_recipients": effective.alert_recipients,
        "alert_delivery_attempts": effective.alert_delivery_attempts,
        "deleted_users": effective.users,
    }


def plan_sha256(preview: CleanupPreview, database_url: str) -> str:
    database = urlsplit(database_url)
    selection = asdict(preview)
    selection["emails"] = sorted(preview.emails)
    selection["missing_emails"] = sorted(preview.missing_emails)
    selection["accounts"] = sorted(selection["accounts"], key=lambda a: str(a["user_id"]))
    selection["clerk_accounts"] = sorted(
        selection["clerk_accounts"], key=lambda a: a["clerk_user_id"]
    )
    plan = {
        "database": [database.hostname, database.port, database.path],
        "preview": selection,
    }
    return _digest(json.dumps(plan, sort_keys=True, default=str))


def delete_accounts(*, raw_emails: str | None, apply: bool, confirm_plan: str | None = None) -> int:
    try:
        emails = parse_emails(raw_emails)
    except EmailInputError as error:
        print_json({"action": ACTION, "status": "invalid", "reason": str(error)})
        return 2

    engine: Engine | None = None
    client: Redis | None = None
    try:
        settings = Settings()
        guarded = settings.account_cleanup_require_confirmation or confirm_plan is not None
        if guarded and raw_emails is None:
            raise AccountCleanupError("explicit_emails_required")
        engine, client, directory = _prepare(settings)
        with engine.connect() as connection:
            preview = build_preview(connection, emails, directory)
        _plan_lines(preview)
        if not preview.accounts and not preview.clerk_accounts:
            print_json(_payload("empty", preview))
            return 1
        token = plan_sha256(preview, settings.database_url) if guarded else None
        if guarded:
            clerk_ids = {account.clerk_user_id for account in preview.clerk_accounts}
            if any(account.clerk_user_id not in clerk_ids for account in preview.accounts):
                raise AccountCleanupError("clerk_identity_mismatch")
        if not apply:
            payload = _payload("preview", preview)
            if guarded:
                payload["plan_sha256"] = token
            print_json(payload)
            return 0
        if guarded and confirm_plan != token:
            raise AccountCleanupError("preview_confirmation_required")

        if guarded:
            accounts, counts = _delete_database(engine, emails, expected=preview)
        else:
            accounts, counts = _delete_database(engine, emails)
        clerk_targets = {account.clerk_user_id: account for account in preview.clerk_accounts}
        for account in accounts:
            clerk_targets.setdefault(
                account.clerk_user_id,
                ClerkAccount(account.clerk_user_id, account.email.casefold()),
            )
        clerk_deleted, clerk_failed = _delete_clerk(directory, clerk_targets.values())

        redis_deleted = 0
        redis_failed = False
        try:
            redis_deleted = _delete_redis(client, accounts)
        except redis.RedisError:
            redis_failed = True

        status = "partial" if clerk_failed or redis_failed else "deleted"
        print_json(
            _payload(
                status,
                preview,
                counts=counts,
                clerk_deleted=clerk_deleted,
                clerk_failed=clerk_failed,
                redis_deleted=redis_deleted,
            )
        )
        return 2 if status == "partial" else 0
    except AccountCleanupError as error:
        print_json({"action": ACTION, "status": "refused", "reason": error.reason})
        return 2
    except ValidationError:
        print_json({"action": ACTION, "status": "refused", "reason": "configuration_invalid"})
        return 2
    except requests.RequestException:
        print_json({"action": ACTION, "status": "failed", "reason": "clerk_unavailable"})
        return 2
    except Exception as error:
        print_json(
            {
                "action": ACTION,
                "status": "failed",
                "reason": type(error).__name__,
            }
        )
        return 2
    finally:
        if client is not None:
            client.close()
        if engine is not None:
            engine.dispose()
