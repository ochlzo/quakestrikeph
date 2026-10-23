"""Exercise the installer's cutover commands without a server or provider access."""

import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class RestoreCutover(unittest.TestCase):
    def run_cutover(self, failed_service="", prediction=2, beat=1):
        source = (ROOT / "infrastructure/scripts/restore-server.sh").read_text()
        commands = source.split(
            '| as_operator gh secret set DEPLOY_KNOWN_HOSTS --repo "$repository"\n',
            1,
        )[1].split("\nsystemctl enable", 1)[0]
        harness = r"""
set -Eeuo pipefail
exec 3>&1
compose() {
    printf 'compose %s\n' "$*"
    if [[ $1 == up && -n $FAILED_SERVICE && " $* " == *" $FAILED_SERVICE "* ]]; then
        return 42
    fi
}
confirm() { printf 'confirm %s\n' "$2"; }
curl() { printf 'curl\n' >&3; }
python3() {
    if [[ $* == *prediction-worker* ]]; then printf '%s\n' "$PREDICTION";
    else printf '%s\n' "$BEAT"; fi
}
docker() { printf 'healthy\n'; }
fail() { return 1; }
backup_dir=fixture
event_id=fixture
"""
        bash = (
            r"C:\Program Files\Git\bin\bash.exe"
            if os.name == "nt"
            else shutil.which("bash")
        )
        return subprocess.run(
            [bash, "-c", harness + commands],
            env={
                **os.environ,
                "FAILED_SERVICE": failed_service,
                "PREDICTION": str(prediction),
                "BEAT": str(beat),
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def test_consumers_are_ready_before_confirmation_and_public_traffic(self):
        result = self.run_cutover()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout
        confirm = output.index("confirm CONNECT")
        ingress = output.index(
            "compose up -d --wait --no-build --pull never cloudflared"
        )
        self.assertLess(output.index("data-ingestor dispatcher"), confirm)
        self.assertLess(output.index("--scale prediction-worker=2"), confirm)
        self.assertLess(confirm, ingress)
        self.assertLess(ingress, output.index("curl"))
        self.assertLess(output.index("curl"), output.index("never beat"))

    def test_failed_consumers_block_cutover(self):
        for service in ("dispatcher", "data-ingestor", "prediction-worker"):
            with self.subTest(service=service):
                result = self.run_cutover(failed_service=service)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("confirm CONNECT", result.stdout)
                self.assertNotIn("cloudflared", result.stdout)
                self.assertNotIn("curl", result.stdout)
                self.assertNotIn("never beat", result.stdout)

    def test_disabled_prediction_and_beat_remain_disabled(self):
        result = self.run_cutover(prediction=0, beat=0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("confirm CONNECT", result.stdout)
        self.assertNotIn("--scale", result.stdout)
        self.assertNotIn("never beat", result.stdout)


if __name__ == "__main__":
    unittest.main()
