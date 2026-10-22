"""Recovery safety checks. These never read production configuration or data."""

import importlib.util
import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "server_transfer", ROOT / "infrastructure/scripts/server-transfer.py"
)
transfer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transfer)


def configuration(root):
    services = {}
    for name in transfer.SERVICES:
        services[name] = {
            "image": "postgres:16.15-bookworm",
            "environment": {
                "DATABASE_URL": "fixture",
                "CLERK_SECRET_KEY": "do-not-forward",
                "IPROG_API_TOKEN": "do-not-forward",
                "BREVO_API_KEY": "do-not-forward",
                "ALERT_RESOLUTION_ENABLED": "true",
                "ALERT_DELIVERY_ENABLED": "true",
            },
            "networks": {"private-data": {}},
            "volumes": [
                {
                    "type": "bind",
                    "source": str(root / "model-artifacts"),
                    "target": "/app/model-artifacts",
                }
            ],
        }
    return {
        "name": "infrastructure",
        "services": services,
        "networks": {"private-data": {"name": "infrastructure_private-data"}},
        "volumes": {
            n: {"name": f"infrastructure_{n}"} for n in ("postgres_data", "redis_data")
        },
    }


def archive(path, entries):
    with tarfile.open(path, "w:gz") as stream:
        for name, contents in entries.items():
            data = contents.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            stream.addfile(member, io.BytesIO(data))


class TransferSafety(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def package(self):
        package = self.root / "package"
        package.mkdir(mode=0o700)
        for name in transfer.FILES:
            (package / name).write_text("fixture")
        transfer.write_json(
            package / "manifest.json",
            {
                "format": 1,
                "id": str(uuid.uuid4()),
                "sha": "a" * 40,
                "repository": str(self.root / "source"),
                "architecture": "fixture",
            },
        )
        transfer.write_json(
            package / "compose.json", configuration(self.root / "source")
        )
        archive(
            package / "application.tar.gz",
            {".env": "FIXTURE=1", "bootstrap-snapshots/bootstrap-readiness.json": "{}"},
        )
        archive(
            package / "host-settings.tar.gz",
            {
                f"etc/quakestrike-backup/{name}": "fixture"
                for name in ("config", "credentials", "restic-password")
            },
        )
        for name in ("postgres_data", "redis_data"):
            archive(package / f"{name}.tar.gz", {"data": "fixture"})
        transfer.seal(package)
        return package

    def test_package_checksums_detect_tampering(self):
        package = self.package()
        transfer.verify(package)
        (package / "images.tar.gz").write_text("changed")
        with self.assertRaisesRegex(ValueError, "Checksum failed"):
            transfer.verify(package)

    def test_missing_and_extra_package_files_are_rejected(self):
        package = self.package()
        (package / "unexpected").write_text("extra")
        with self.assertRaisesRegex(ValueError, "Unlisted"):
            transfer.verify(package)
        (package / "unexpected").unlink()
        (package / "redis_data.tar.gz").unlink()
        transfer.seal(package)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            transfer.verify(package)

    def test_path_traversal_and_links_are_rejected_before_extraction(self):
        path = self.root / "bad.tar.gz"
        for name in ("../outside", "/etc/passwd", "data/../../outside"):
            archive(path, {name: "bad"})
            with self.assertRaisesRegex(ValueError, "Unsafe archive"):
                transfer.safe_members(path)
        with tarfile.open(path, "w:gz") as stream:
            member = tarfile.TarInfo("link")
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/passwd"
            stream.addfile(member)
        with self.assertRaisesRegex(ValueError, "Links"):
            transfer.safe_members(path)

    def test_rehearsal_excludes_writers_credentials_and_external_networks(self):
        package = self.package()
        original = (package / "compose.json").read_bytes()
        owner = str(uuid.uuid4())
        config = transfer.restore_config(package, self.root / "rehearsal", True, owner)
        self.assertEqual(set(config["services"]), transfer.READERS)
        self.assertEqual(
            config["services"]["bulletin"]["environment"]["API_TARGET"],
            "http://backend-api:3000",
        )
        self.assertTrue(all(n["internal"] for n in config["networks"].values()))
        for service in config["services"].values():
            self.assertNotIn("ports", service)
            self.assertEqual(service["labels"][transfer.LABEL], owner)
            self.assertNotIn("do-not-forward", service["environment"].values())
            self.assertEqual(service["environment"]["ALERT_DELIVERY_ENABLED"], "false")
        self.assertTrue(
            all(
                v["name"].startswith("quakestrike-restore-test_")
                for v in config["volumes"].values()
            )
        )
        self.assertEqual((package / "compose.json").read_bytes(), original)

    def test_live_configuration_keeps_delivery_disabled_and_original_images(self):
        package = self.package()
        config = transfer.restore_config(package, self.root / "new", False, "owner")
        self.assertIn("cloudflared", config["services"])
        for service in config["services"].values():
            self.assertEqual(service["environment"]["ALERT_DELIVERY_ENABLED"], "false")
            self.assertEqual(service["image"], "postgres:16.15-bookworm")
            self.assertEqual(service["environment"]["ALERT_TEST_REDIS_URL"], "")

    def test_external_mounts_and_public_ports_are_rejected(self):
        config = configuration(self.root)
        config["services"]["postgres"]["ports"] = [{"published": "5432"}]
        with self.assertRaisesRegex(ValueError, "Public ports"):
            transfer.config_valid(config, self.root)
        config["services"]["postgres"].pop("ports")
        config["services"]["postgres"]["volumes"][0]["source"] = str(
            self.root.parent / "other"
        )
        with self.assertRaisesRegex(ValueError, "outside"):
            transfer.config_valid(config, self.root)

    def test_cleanup_checks_every_owner_before_deleting_anything(self):
        found = [
            ("container", "one", {"Config": {"Labels": {transfer.LABEL: "ours"}}}),
            ("volume", "two", {"Labels": {transfer.LABEL: "somebody-else"}}),
        ]
        with (
            patch.object(transfer, "resources", return_value=iter(found)),
            patch.object(subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(ValueError, "different owner"):
                transfer.cleanup(transfer.REHEARSAL, "ours")
            run.assert_not_called()
        with self.assertRaisesRegex(ValueError, "restricted"):
            transfer.cleanup("infrastructure", "ours")

    def test_existing_even_empty_volume_refuses_installation(self):
        with (
            patch.object(
                transfer, "resources", return_value=iter([("volume", "empty", {})])
            ),
            self.assertRaisesRegex(ValueError, "Existing"),
        ):
            transfer.empty_project("infrastructure")

    def test_existing_installation_refuses_before_docker_mutation(self):
        with (
            patch.object(os.path, "lexists", return_value=True),
            patch.object(transfer, "docker") as docker,
        ):
            with self.assertRaisesRegex(ValueError, "already exists"):
                transfer.fresh_host()
            docker.assert_not_called()

    def test_unlabelled_volume_names_also_refuse_rehearsal(self):
        with (
            patch.object(transfer, "resources", return_value=iter([])),
            patch.object(
                transfer,
                "docker",
                return_value="quakestrike-restore-test_postgres_data",
            ),
            self.assertRaisesRegex(ValueError, "unlabelled"),
        ):
            transfer.empty_project(transfer.REHEARSAL)

    def test_required_test_reports_cannot_hide_skips_or_zero_tests(self):
        report = self.root / "report.xml"
        for xml in (
            "<testsuite/>",
            '<testsuite><testcase name="real-model"><skipped/></testcase></testsuite>',
            '<testsuite><testcase name="failure"><failure/></testcase></testsuite>',
        ):
            report.write_text(xml)
            with self.assertRaises(ValueError):
                transfer.check_junit(report)
        report.write_text('<testsuite><testcase name="passed"/></testsuite>')
        transfer.check_junit(report)

    def test_shell_entrypoints_parse_and_help_without_server_access(self):
        bash = shutil.which("bash")
        if os.name == "nt":
            bash = r"C:\Program Files\Git\bin\bash.exe"
        for name in (
            "backup-server.sh",
            "restore-server.sh",
            "server-transfer-common.sh",
            "server-transfer-tests.sh",
        ):
            path = ROOT / "infrastructure/scripts" / name
            subprocess.run([bash, "-n", str(path)], check=True)
        for name in ("backup-server.sh", "restore-server.sh"):
            result = subprocess.run(
                [bash, str(ROOT / "infrastructure/scripts" / name), "--help"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Usage:", result.stdout)


if __name__ == "__main__":
    unittest.main()
