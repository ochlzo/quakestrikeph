"""The observer password must cross the Windows subprocess boundary unchanged."""

import runpy
import subprocess
from pathlib import Path


def test_observer_password_is_sent_as_bytes(monkeypatch):
    script = Path(__file__).resolve().parents[3] / "infrastructure/scripts/create-observer.py"
    main = runpy.run_path(str(script))["main"]
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if "config" in args:
            return subprocess.CompletedProcess(
                args, 0, stdout="OBSERVER_DB_PASSWORD=secret-value\n"
            )
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert main() == 0
    assert calls[1][1]["input"] == b"secret-value\n"
    assert not calls[1][1].get("text", False)
