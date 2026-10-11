import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("previous_bulletin", "failure", "active_alerts"),
    [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (True, True, False),
        (True, False, True),
    ],
)
def test_bulletin_rollout_restores_or_saves_tags(
    tmp_path, previous_bulletin, failure, active_alerts
):
    bash = shutil.which("bash")
    if os.name == "nt":
        bash = "C:/Program Files/Git/bin/bash.exe"
    if not bash or not Path(bash).exists():
        pytest.skip("Bash is unavailable")
    old = "a" * 40
    new = "b" * 40
    env = f"WORKER_IMAGE_TAG={old}\n"
    if previous_bulletin:
        env += f"BULLETIN_IMAGE_TAG={old}\n"
    (tmp_path / ".env").write_text(env)
    script = Path("infrastructure/scripts/deploy-workers.sh").read_text()
    script = script.replace("cd /srv/quakestrikeph", f"cd '{tmp_path.as_posix()}'")
    script = script.replace(
        "source infrastructure/scripts/enable-beat.sh", "release_enable_beat() { :; }"
    )
    mocks = r"""
old=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
new=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
log() { printf "%s\n" "$*" >> commands.log; }
git() {
    log "git $*"
    case "$*" in
        "status "*) ;;
        "rev-parse HEAD") echo "$old" ;;
        "rev-parse FETCH_HEAD") echo "$new" ;;
    esac
}
docker() {
    log "docker $*"
    if [[ $* == *"inspect --format"* ]]; then
        echo "${!#}" | sed 's/.*://'
    elif [[ $* == *"ps --status running -q"* ]]; then
        case "${!#}" in prediction-worker|beat|alert-reconciliation) ;; *) echo container ;; esac
    fi
}
curl() { log "curl $*"; return 22; }
"""
    test_script = tmp_path / "deploy.sh"
    if active_alerts:
        mocks = mocks.replace("|alert-reconciliation", "")
    if not failure:
        mocks = mocks.replace("return 22", "return 0")
    test_script.write_text(mocks + script)
    result = subprocess.run([bash, str(test_script), new], capture_output=True, text=True)
    if active_alerts:
        assert result.returncode == 2
        assert "explicit alert-runtime rollout" in result.stderr
        assert (tmp_path / ".env").read_text() == env
        commands = (tmp_path / "commands.log").read_text()
        assert "git fetch" not in commands and "git switch" not in commands
        return
    if not failure:
        assert result.returncode == 0, result.stderr
        saved = (tmp_path / ".env").read_text()
        assert f"WORKER_IMAGE_TAG={new}" in saved
        assert f"BULLETIN_IMAGE_TAG={new}" in saved
        return
    assert result.returncode == 22, result.stderr
    assert (tmp_path / ".env").read_text() == env
    commands = (tmp_path / "commands.log").read_text()
    assert f"git switch --detach {old}" in commands
    assert "--force-recreate traefik" in commands
    if previous_bulletin:
        assert commands.count("up -d --wait --no-deps bulletin") == 2
    else:
        assert "stop bulletin" in commands
        assert "rm -f bulletin" in commands
