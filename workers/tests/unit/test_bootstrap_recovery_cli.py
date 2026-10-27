"""Operator command argument handling for bootstrap recovery."""

from __future__ import annotations

import sys

import pytest

from quakestrike import cli, operator_bootstrap_recovery


@pytest.mark.parametrize(("flag", "apply"), [("--check", False), ("--apply", True)])
def test_recovery_cli_requires_an_explicit_mode(monkeypatch, flag, apply):
    received = {}

    def run(**kwargs):
        received.update(kwargs)
        return 0

    monkeypatch.setattr(operator_bootstrap_recovery, "recover_bootstrap_readiness", run)
    monkeypatch.setattr(sys, "argv", ["quakestrike", "recover-bootstrap-readiness", flag])
    assert cli.main() == 0
    assert received["apply"] is apply


@pytest.mark.parametrize("flags", [[], ["--check", "--apply"]])
def test_recovery_cli_rejects_ambiguous_mode(monkeypatch, flags):
    monkeypatch.setattr(sys, "argv", ["quakestrike", "recover-bootstrap-readiness", *flags])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
