"""Round-trip disposable Docker data, including refusal to overwrite a populated volume."""

import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path


class VolumeRoundTrip(unittest.TestCase):
    def test_round_trip_and_overwrite_refusal(self):
        token = uuid.uuid4().hex
        names = [
            f"qs-transfer-fixture-{token}-{suffix}" for suffix in ("source", "target")
        ]
        image = "postgres:16.15-bookworm"

        def docker(*args, check=True):
            return subprocess.run(
                ["docker", *args], check=check, capture_output=True, text=True
            )

        with tempfile.TemporaryDirectory() as directory:
            try:
                for name in names:
                    docker(
                        "volume",
                        "create",
                        "--label",
                        f"io.quakestrike.transfer={token}",
                        name,
                    )
                docker(
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--user",
                    "0",
                    "-v",
                    f"{names[0]}:/data",
                    "--entrypoint",
                    "sh",
                    image,
                    "-ec",
                    "printf 'fixture-data' > /data/record; chown 10001:10001 /data/record; chmod 600 /data/record",
                )
                mount = f"type=bind,src={Path(directory).resolve()},dst=/backup"
                docker(
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--user",
                    "0",
                    "-v",
                    f"{names[0]}:/source:ro",
                    "--mount",
                    mount,
                    "--entrypoint",
                    "tar",
                    image,
                    "-czpf",
                    "/backup/data.tar.gz",
                    "-C",
                    "/source",
                    ".",
                )
                command = [
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--user",
                    "0",
                    "-v",
                    f"{names[1]}:/restore",
                    "--mount",
                    mount,
                    "--entrypoint",
                    "sh",
                    image,
                    "-ec",
                    'test -z "$(ls -A /restore)"; tar -xzpf /backup/data.tar.gz -C /restore',
                ]
                docker(*command)
                result = docker(
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--user",
                    "0",
                    "-v",
                    f"{names[1]}:/data:ro",
                    "--entrypoint",
                    "sh",
                    image,
                    "-ec",
                    "cat /data/record; stat -c ' %u:%g %a' /data/record",
                )
                self.assertEqual(result.stdout.strip(), "fixture-data 10001:10001 600")
                self.assertNotEqual(docker(*command, check=False).returncode, 0)
            finally:
                for name in names:
                    result = docker(
                        "volume",
                        "inspect",
                        "--format",
                        '{{index .Labels "io.quakestrike.transfer"}}',
                        name,
                        check=False,
                    )
                    if result.returncode == 0 and result.stdout.strip() == token:
                        docker("volume", "rm", name)


if __name__ == "__main__":
    unittest.main()
