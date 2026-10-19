from __future__ import annotations

import hashlib
import json
import sys
from unittest.mock import Mock
from uuid import uuid4

import pytest
import redis
import requests

from quakestrike import cli, operator_accounts
from quakestrike.operator_accounts import (
    DEFAULT_EMAILS,
    EmailInputError,
    LocalAccount,
    parse_emails,
    phone_keys,
)


def test_missing_flag_uses_the_five_default_addresses() -> None:
    assert parse_emails(None) == (
        "johnthetester1@proton.me",
        "johnbenedictkandelarya@gmail.com",
        "jbbc2023-4132-17459@bicol-u.edu.ph",
        "cholocandelaria123@gmail.com",
        "cholocandelaria@proton.me",
    )
    assert DEFAULT_EMAILS[0] == "johnthetester1@proton.me"


def test_comma_separated_input_is_trimmed_folded_and_unique() -> None:
    assert parse_emails("A@Example.test, b@example.test , A@example.TEST") == (
        "a@example.test",
        "b@example.test",
    )


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "  ",
        "a@example.test,",
        "a@example.test,,b@example.test",
        "a@example.test b@example.test",
        "not-an-address",
    ],
)
def test_malformed_input_is_rejected(raw: str) -> None:
    with pytest.raises(EmailInputError):
        parse_emails(raw)


def test_more_than_one_hundred_addresses_is_rejected() -> None:
    raw = ",".join(f"user{index}@example.test" for index in range(101))
    with pytest.raises(EmailInputError):
        parse_emails(raw)


def test_phone_keys_hash_identifiers_and_include_the_suffix_family() -> None:
    keys = phone_keys([LocalAccount(uuid4(), "user_abc", "reader@example.test", "+639171234567")])

    assert len(keys) == 10
    assert sum(key.startswith("bulletin:phone:user:") for key in keys) == 5
    assert sum(key.startswith("bulletin:phone:owner:") for key in keys) == 5
    assert all("+639171234567" not in key for key in keys)
    assert all("user_abc" not in key for key in keys)


def test_phone_keys_skip_the_owner_family_without_a_number() -> None:
    keys = phone_keys([LocalAccount(uuid4(), "user_abc", "reader@example.test", None)])

    assert len(keys) == 5
    assert all(key.startswith("bulletin:phone:user:") for key in keys)


def test_cli_routes_the_flag_to_the_command(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_delete_accounts(*, raw_emails: str | None, apply: bool) -> int:
        captured.update(raw_emails=raw_emails, apply=apply)
        return 0

    monkeypatch.setattr(operator_accounts, "delete_accounts", fake_delete_accounts)
    monkeypatch.setattr(
        sys,
        "argv",
        ["quakestrike", "delete-accounts", "--emails", "a@example.test", "--apply"],
    )

    assert cli.main() == 0
    assert captured == {"raw_emails": "a@example.test", "apply": True}


@pytest.mark.parametrize("saved_phone", [None, "+639181234567", "+639171234567"])
def test_redis_cleanup_removes_saved_and_pending_phone_families(saved_phone) -> None:
    account = LocalAccount(uuid4(), "user_pending", "reader@example.test", saved_phone)
    pending_phone = "+639171234567"
    user_key = "bulletin:phone:user:" + hashlib.sha256(b"user_pending").hexdigest()
    owner_key = "bulletin:phone:owner:" + hashlib.sha256(pending_phone.encode()).hexdigest()
    expected = set(phone_keys([account])) | {
        owner_key + suffix for suffix in ("", ":lock", ":cooldown", ":hour", ":day")
    }
    stored = dict.fromkeys(expected, b"fixture")
    stored[user_key] = json.dumps({"phone": pending_phone, "owner": owner_key}).encode()
    stored["unrelated"] = b"keep"
    client = Mock()
    client.get.side_effect = stored.get

    def delete(*keys):
        assert user_key in stored, "Read pending state before deleting the user key."
        for key in keys:
            stored.pop(key)
        return len(keys)

    client.delete.side_effect = delete
    assert operator_accounts._delete_redis(client, [account]) == len(expected)
    assert stored == {"unrelated": b"keep"}


@pytest.fixture
def cleanup(monkeypatch):
    account = LocalAccount(uuid4(), "user_cleanup", "reader@example.test", None)
    clerk_only = operator_accounts.ClerkAccount("user_clerk_only", "other@example.test")
    preview = operator_accounts.CleanupPreview(
        (account.email, clerk_only.email), (account,), (clerk_only,), ()
    )
    engine, client, directory = Mock(), Mock(), Mock()
    engine.connect.return_value.__enter__ = Mock(return_value=Mock())
    engine.connect.return_value.__exit__ = Mock(return_value=False)
    client.get.return_value = None
    client.delete.return_value = 0
    directory.delete.return_value = True
    monkeypatch.setattr(operator_accounts, "Settings", Mock())
    prepare = Mock(return_value=(engine, client, directory))
    monkeypatch.setattr(operator_accounts, "_prepare", prepare)
    monkeypatch.setattr(operator_accounts, "build_preview", Mock(return_value=preview))
    database = Mock(return_value=((account,), operator_accounts.DeletionCounts(users=1)))
    monkeypatch.setattr(operator_accounts, "_delete_database", database)
    return account, clerk_only, client, directory, prepare, database


def test_preview_does_not_delete_from_any_system(cleanup, capsys) -> None:
    _, _, client, directory, _, database = cleanup
    assert operator_accounts.delete_accounts(raw_emails=None, apply=False) == 0
    database.assert_not_called()
    directory.delete.assert_not_called()
    client.delete.assert_not_called()
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["status"] == "preview"


def test_preflight_refusal_does_not_delete_from_any_system(cleanup, capsys) -> None:
    _, _, client, directory, prepare, database = cleanup
    prepare.side_effect = operator_accounts.AccountCleanupError("redis_unavailable")
    assert operator_accounts.delete_accounts(raw_emails=None, apply=True) == 2
    database.assert_not_called()
    directory.delete.assert_not_called()
    client.delete.assert_not_called()
    assert json.loads(capsys.readouterr().out)["status"] == "refused"


@pytest.mark.parametrize("failure", [None, "clerk", "redis"])
def test_apply_cleans_all_systems_and_reports_partial_failures(cleanup, capsys, failure) -> None:
    account, clerk_only, client, directory, _, database = cleanup
    order = []

    def delete_database(*_):
        order.append("database")
        return (account,), operator_accounts.DeletionCounts(users=1)

    database.side_effect = delete_database

    def delete_clerk(user_id):
        order.append("clerk")
        if failure == "clerk" and user_id == account.clerk_user_id:
            raise requests.ConnectionError("fixture outage")
        return True

    def delete_redis(*keys):
        order.append("redis")
        if failure == "redis":
            raise redis.ConnectionError("fixture outage")
        return len(keys)

    directory.delete.side_effect = delete_clerk
    client.delete.side_effect = delete_redis
    assert operator_accounts.delete_accounts(raw_emails=None, apply=True) == (2 if failure else 0)
    assert order == ["database", "clerk", "clerk", "redis"]
    assert {call.args[0] for call in directory.delete.call_args_list} == {
        account.clerk_user_id,
        clerk_only.clerk_user_id,
    }
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["status"] == ("partial" if failure else "deleted")
    assert result["clerk_users_failed"] == (
        [{"clerk_user_id": account.clerk_user_id, "email": account.email}]
        if failure == "clerk"
        else []
    )


def test_clerk_adapter_filters_matches_and_accepts_an_already_deleted_user() -> None:
    session = Mock()
    session.get.return_value.json.return_value = [
        {"id": "user_match", "email_addresses": [{"email_address": "Reader@Example.test"}]},
        {"id": "user_other", "email_addresses": [{"email_address": "other@example.test"}]},
    ]
    session.delete.return_value.status_code = 404
    directory = operator_accounts.HttpClerkDirectory("fixture", session=session)
    assert directory.find_by_email(["reader@example.test"]) == (
        operator_accounts.ClerkAccount("user_match", "reader@example.test"),
    )
    assert directory.delete("user_match") is False
    session.delete.return_value.raise_for_status.assert_not_called()
