import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("exists", "cleanup", "lifecycle", "concurrent_start", "failure", "success"),
    [
        ("0", "", "", False, "none", True),
        ("1", "complete", "closed", False, "none", True),
        ("1", "complete", "expired", False, "none", True),
        ("1", "none", "active", False, "none", False),
        ("1", "pending", "closed", False, "none", False),
        ("1", "failed", "closed", False, "none", False),
        ("1", "complete", "active", False, "none", False),
        ("ERR unavailable", "", "", False, "none", False),
        ("0", "", "", True, "none", False),
        ("1", "complete", "closed", False, "missing-redis", False),
        ("1", "complete", "closed", False, "control-stop", False),
        ("1", "complete", "closed", False, "final-check", False),
    ],
)
def test_deployment_stops_only_optional_services_after_cleanup(
    tmp_path, exists, cleanup, lifecycle, concurrent_start, failure, success
):
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    if not bash or not Path(bash).exists():
        pytest.skip("Bash is unavailable")
    script = Path("infrastructure/scripts/stop-optional-services.sh").resolve().as_posix()
    command = r"""
set -Eeuo pipefail
docker() {
    printf '%s\n' "$*" >> "$TRACE"
    if [[ $1 == ps ]]; then
        [[ $* == *label=com.docker.compose.project=infrastructure* ]] || return 9
        for arg in "$@"; do
            if [[ $arg == label=com.docker.compose.service=* ]]; then
                if [[ $arg == *service=alert-test-redis && $FAILURE == missing-redis ]]; then
                    continue
                fi
                if [[ $arg == *service=pgadmin && $CONCURRENT_START == true
                      && ! -f "$CONTROL_STOPPED" ]]; then
                    touch "$NEW_SESSION"
                fi
                printf 'container-%s\n' "${arg##*=}"
            fi
        done
    elif [[ $1 == exec ]]; then
        if [[ $FAILURE == final-check && -f "$CONSUMER_STOPPED" ]]; then
            printf 'ERR unavailable\n'
            return
        fi
        if [[ -f "$NEW_SESSION" ]]; then
            SESSION_EXISTS=1
            SESSION_CLEANUP=none
            SESSION_LIFECYCLE=active
        fi
        case "$*" in
            *EXISTS*) printf '%s\n' "$SESSION_EXISTS" ;;
            *cleanup) printf '%s\n' "$SESSION_CLEANUP" ;;
            *lifecycle) printf '%s\n' "$SESSION_LIFECYCLE" ;;
        esac
    elif [[ $1 == stop && $* == *container-alert-test-control* ]]; then
        [[ $FAILURE != control-stop ]] || return 9
        touch "$CONTROL_STOPPED"
    elif [[ $1 == stop && $* == *container-alert-test-consumer* ]]; then
        touch "$CONSUMER_STOPPED"
    elif [[ $1 == start && $* == *container-alert-test-control* ]]; then
        rm -f "$CONTROL_STOPPED"
    fi
}
source "$1"
stop_optional_services
"""
    trace = tmp_path / "commands.log"
    result = subprocess.run(
        [bash, "-c", command, "test", script],
        env={
            **os.environ,
            "TRACE": trace.as_posix(),
            "SESSION_EXISTS": exists,
            "SESSION_CLEANUP": cleanup,
            "SESSION_LIFECYCLE": lifecycle,
            "CONCURRENT_START": str(concurrent_start).lower(),
            "CONTROL_STOPPED": (tmp_path / "control-stopped").as_posix(),
            "NEW_SESSION": (tmp_path / "new-session").as_posix(),
            "CONSUMER_STOPPED": (tmp_path / "consumer-stopped").as_posix(),
            "FAILURE": failure,
        },
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is success, result.stderr
    commands = trace.read_text().splitlines()
    stops = [line for line in commands if line.startswith("stop ")]
    control_stop = "stop --time 20 container-alert-test-control"
    assert stops[0] == control_stop
    probes = [i for i, line in enumerate(commands) if line.startswith("exec ")]
    if probes:
        assert commands.index(control_stop) < min(probes)
    other_stop = (
        "stop --time 20 container-pgadmin container-alert-test-consumer container-alert-test-relay"
    )
    if success:
        assert stops == [control_stop, other_stop, "stop --time 20 container-alert-test-redis"]
        assert not any(line.startswith("start ") for line in commands)
    elif failure == "final-check":
        assert stops == [control_stop, other_stop]
        assert not any(line.startswith("start ") for line in commands)
    else:
        assert stops == [control_stop]
        assert ("start container-alert-test-control" in commands) is (failure != "control-stop")
