from __future__ import annotations

import sys
from uuid import uuid4

import pytest

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
