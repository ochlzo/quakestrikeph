import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("previous_bulletin", "failure", "active_alerts", "schema_change", "legacy_release"),
    [
        (False, False, False, False, False),
        (True, False, False, False, False),
        (False, True, False, False, False),
        (True, True, False, False, False),
        (True, False, True, False, False),
        (True, True, True, True, False),
        (True, "backup", False, False, False),
        (True, "restore", False, False, False),
        (True, "consumer", False, False, False),
        (True, "backend", True, False, False),
        (True, False, False, False, True),
        (True, "cleanup", False, False, False),
        (True, "quakestrikeph.com", False, False, False),
        (False, "quakestrikeph.com", False, False, False),
    ],
)
def test_bulletin_rollout_restores_or_saves_tags(
    tmp_path, previous_bulletin, failure, active_alerts, schema_change, legacy_release
):
    bash = shutil.which("bash")
    if os.name == "nt":
        bash = "C:/Program Files/Git/bin/bash.exe"
    if not bash or not Path(bash).exists():
        pytest.skip("Bash is unavailable")
    old = "a" * 40
    new = "b" * 40
    env = (
        f"WORKER_IMAGE_TAG={old}\nBACKEND_IMAGE_TAG={old}\n"
        "ALERT_DELIVERY_ENABLED=false\nPRIVATE_VALUE=preserved\n"
    )
    if previous_bulletin:
        env += f"BULLETIN_IMAGE_TAG={old}\n"
    (tmp_path / ".env").write_text(env)
    script = Path("infrastructure/scripts/deploy-workers.sh").read_text()
    script = script.replace("cd /srv/quakestrikeph", f"cd '{tmp_path.as_posix()}'")
    script = script.replace(
        "source infrastructure/scripts/enable-beat.sh", "release_enable_beat() { :; }"
    )
    scripts = tmp_path / "infrastructure/scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(
        "infrastructure/scripts/stop-optional-services.sh", scripts / "stop-optional-services.sh"
    )
    cutover = tmp_path / ".local/domain-cutover"
    if failure == "quakestrikeph.com":
        cutover.mkdir(parents=True)
        shutil.copyfile("infrastructure/traefik/backend.yml", cutover / "backend.yml")
        shutil.copyfile("infrastructure/compose.domain-cutover.yml", cutover / "compose.yml")
    shutil.copyfile("infrastructure/scripts/save-release-tags.py", scripts / "save-release-tags.py")
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
    if [[ $* == *compose.backend.yml* && -n ${ALERT_TEST_REDIS_URL:-} ]]; then
        echo 'Deployment must disable the optional test Redis connection' >&2
        return 26
    fi
    if [[ $* == *"{{.Image}}"* || $* == *"{{.Id}}"* ]]; then
        echo sha256:previous-backend
    elif [[ $* == *"inspect --format"* ]]; then
        echo "${!#}" | sed 's/.*://'
    elif [[ $* == *"config --services"* ]]; then
        printf 'alert-worker\nalert-reconciliation\n'
    elif [[ $* == *"ps --status running -q"* ]]; then
        case "${!#}" in
            prediction-worker|beat|alert-worker|alert-reconciliation) ;;
            *) echo container ;;
        esac
    elif [[ $* == *"config --format json"* ]]; then
        echo '{"services":{"alert-worker":{"environment":{
            "ALERT_RESOLUTION_ENABLED":"true","ALERT_DELIVERY_ENABLED":"true"}}}}'
    elif [[ $* == *"SELECT version_num"* ]]; then
        cat >/dev/null
        if [[ -f schema-changed ]]; then echo new-revision; else echo old-revision; fi
    fi
}
sudo() { log "sudo $*"; }
python3() {
    log "python3 $*"
    if [[ $1 == infrastructure/scripts/cleanup-release-images.py ]]; then return 0; fi
    command "$PYTHON_FOR_TEST" "$@"
}
curl() { log "curl $*"; return 22; }
"""
    if legacy_release:
        mocks = mocks.replace("printf 'alert-worker\\nalert-reconciliation\\n'", "echo dispatcher")
        mocks = mocks.replace(
            'log "docker $*"',
            'log "docker $*"; [[ $* != *"ps --status running -q alert"* ]] || return 25',
        )
    if active_alerts:
        mocks = mocks.replace("|alert-worker|alert-reconciliation", "")
    if schema_change:
        mocks = mocks.replace(
            'sudo() { log "sudo $*"; }',
            'sudo() { log "sudo $*"; [[ $* != *"flock"* ]] || touch schema-changed; }',
        )
    if failure in ("backup", "restore"):
        service = "backup" if failure == "backup" else "restore-test"
        mocks = mocks.replace(
            'sudo() { log "sudo $*"; }',
            f'sudo() {{ log "sudo $*"; [[ $* != *"quakestrike-postgres-{service}.service"* ]]; }}',
        )
    if failure == "cleanup":
        mocks = mocks.replace("then return 0; fi", "then return 27; fi")
    if not failure or failure == "cleanup":
        mocks = mocks.replace("return 22", "return 0")
    if failure == "quakestrikeph.com":
        mocks = mocks.replace(
            'curl() { log "curl $*"; return 22; }',
            f'curl() {{ log "curl $*"; [[ $* != *"https://{failure}/"* ]] || return 22; }}',
        )
    if failure == "consumer":
        mocks = mocks.replace(
            'log "docker $*"',
            'log "docker $*"; [[ $* != *"up -d --wait --no-deps data-ingestor"* ]] || return 23',
        )
    if failure == "backend":
        mocks = mocks.replace(
            'log "docker $*"',
            'log "docker $*"; [[ $* != *"up -d --wait --no-deps backend-api"* ]] || return 24',
        )
    import sys

    result = subprocess.run(
        [bash, "-s", "--", new],
        input=mocks + script,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHON_FOR_TEST": sys.executable,
            "ALERT_TEST_REDIS_URL": "redis://optional-test:6379/0",
            "HOME": str(tmp_path),
            "USERPROFILE": str(tmp_path),
        },
    )
    commands = (tmp_path / "commands.log").read_text()
    if failure and failure != "cleanup":
        assert "cleanup-release-images.py" not in commands
    if failure in ("backup", "restore"):
        assert result.returncode != 0
        assert " stop " not in commands
        assert "prepare-release-database.sh" not in commands
        assert (tmp_path / ".env").read_text() == env
        return
    assert commands.index("quakestrike-postgres-backup.service") < commands.index(
        "stop backend-api"
    )
    assert commands.index("quakestrike-postgres-restore-test.service") < commands.index(
        "prepare-release-database.sh"
    )
    if failure in ("consumer", "backend"):
        assert result.returncode == (23 if failure == "consumer" else 24), result.stderr
        assert "up -d --wait --no-deps dispatcher" not in commands
        assert "up -d --wait --no-deps alert-worker" not in commands
        assert (tmp_path / ".env").read_text() == env
        return
    assert (
        commands.index("stop backend-api")
        < commands.index("prepare-release-database.sh")
        < commands.index("startup-check")
        < commands.index("up -d --wait --no-deps backend-api")
    )
    if active_alerts:
        assert "up -d --wait --no-deps alert-reconciliation" in commands
        assert (
            commands.index("up -d --wait --no-deps alert-reconciliation")
            < commands.index("up -d --wait --no-deps alert-worker")
            < commands.index("up -d --wait --no-deps dispatcher")
        )
    else:
        assert "up -d --wait --no-deps alert-worker" not in commands
    if schema_change:
        assert result.returncode == 22
        assert "Repair forward" in result.stderr
        assert f"git switch --detach {old}" not in commands
        assert (tmp_path / ".env").read_text() == env
        return
    if not failure or failure == "cleanup":
        assert result.returncode == 0, result.stderr
        assert "https://quakestrikeph.com/ -o /dev/null" in commands
        assert "https://quakestrikeph.com/api/v1/earthquakes/search" in commands
        assert "quakestrikeph.qzz.io" not in commands
        saved = (tmp_path / ".env").read_text()
        assert f"WORKER_IMAGE_TAG={new}" in saved
        assert f"BULLETIN_IMAGE_TAG={new}" in saved
        assert f"BACKEND_IMAGE_TAG={new}" in saved
        assert "ALERT_DELIVERY_ENABLED=false\nPRIVATE_VALUE=preserved" in saved
        assert commands.index("save-release-tags.py") < commands.index("cleanup-release-images.py")
        assert commands.index("curl ") < commands.index("cleanup-release-images.py")
        assert "Deployment failed" not in result.stderr
        if failure == "cleanup":
            assert "::warning::Deployment succeeded" in result.stderr
        return
    assert result.returncode == 22, result.stderr
    assert (tmp_path / ".env").read_text() == env
    commands = (tmp_path / "commands.log").read_text()
    assert f"git switch --detach {old}" in commands
    assert "--force-recreate traefik" in commands
    if failure == "quakestrikeph.com":
        rollback_commands = commands.split(f"git switch --detach {old}\n", 1)[1]
        traefik_commands = [
            command
            for command in rollback_commands.splitlines()
            if "--force-recreate traefik" in command
        ]
        assert traefik_commands
        assert all("-f .local/domain-cutover/compose.yml" in c for c in traefik_commands)
        if previous_bulletin:
            bulletin_commands = [
                c for c in rollback_commands.splitlines() if "up -d --wait --no-deps bulletin" in c
            ]
            assert bulletin_commands
            assert all("-f .local/domain-cutover/compose.yml" in c for c in bulletin_commands)
        routes = (cutover / "backend.yml").read_text()
        assert "Host(`quakestrikeph.com`)" in routes
        assert "quakestrikeph.qzz.io" not in routes
    if previous_bulletin:
        assert commands.count("up -d --wait --no-deps bulletin") == 2
    else:
        assert "stop bulletin" in commands
        assert "rm -f bulletin" in commands
