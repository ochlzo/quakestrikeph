import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("failure", [None, "migration", "worker-grants", "wrong-checkout"])
def test_release_database_preparation_stops_at_first_failure(tmp_path, failure):
    bash = shutil.which("bash")
    if os.name == "nt":
        bash = "C:/Program Files/Git/bin/bash.exe"
    if not bash or not Path(bash).exists():
        pytest.skip("Bash is unavailable")
    scripts = tmp_path / "database/initialization"
    scripts.mkdir(parents=True)
    (scripts / "provision-roles.sh").write_text("# reviewed grants\n")
    sha = "b" * 40
    script = Path("database/initialization/prepare-release-database.sh").read_text()
    script = script.replace("cd /srv/quakestrikeph", f"cd '{tmp_path.as_posix()}'")
    mocks = r"""
git() { echo bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb; }
docker() {
    printf '%s\n' "$*" >> commands.log
    [[ $WORKER_IMAGE_TAG == bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb ]] || return 99
    if [[ $* == *"sh -s"* ]]; then
        [[ $(cat) == '# reviewed grants' ]] || return 98
    fi
}
"""
    if failure == "wrong-checkout":
        mocks = mocks.replace("echo bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "echo wrong")
    elif failure:
        command = "quakestrike migrate" if failure == "migration" else "sh -s grant-worker"
        mocks = mocks.replace("docker() {", f'docker() {{ [[ $* != *"{command}"* ]] || return 23;')
    test_script = tmp_path / "prepare.sh"
    test_script.write_text(mocks + script)
    result = subprocess.run([bash, str(test_script), sha], capture_output=True, text=True)
    commands_path = tmp_path / "commands.log"
    commands = commands_path.read_text() if commands_path.exists() else ""
    if failure:
        assert result.returncode == (2 if failure == "wrong-checkout" else 23), result.stderr
        assert "sh -s create-backend" not in commands
        if failure in ("migration", "wrong-checkout"):
            assert "sh -s grant-worker" not in commands
    else:
        assert result.returncode == 0, result.stderr
        assert (
            commands.index("quakestrike migrate")
            < commands.index("sh -s grant-worker")
            < commands.index("sh -s create-backend")
        )
