import subprocess
import sys


def test_worker_health_does_not_load_operator_or_ingestion_commands():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import quakestrike.operator_runtime; "
            "assert not {'quakestrike.cli', 'quakestrike.operator_accounts', "
            "'quakestrike.infrastructure.database.repositories', "
            "'quakestrike.infrastructure.startup', "
            "'quakestrike.scheduler.dispatcher'} & sys.modules.keys()",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_worker_health_entry_point_rejects_mutating_commands():
    result = subprocess.run(
        [sys.executable, "-m", "quakestrike.operator_runtime", "poll-now"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stderr
