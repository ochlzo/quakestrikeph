"""Validate recovery files and generate isolated Compose configuration. Standard library only."""

import copy
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

LABEL = "io.quakestrike.transfer"
REHEARSAL = "quakestrike-restore-test"
SERVICES = {
    "postgres",
    "redis",
    "release-init",
    "backend-api",
    "bulletin",
    "traefik",
    "cloudflared",
    "dispatcher",
    "data-ingestor",
    "prediction-worker",
    "beat",
    "alert-worker",
    "alert-reconciliation",
}
READERS = {"postgres", "redis", "release-init", "backend-api", "bulletin", "traefik"}
FILES = {
    "manifest.json",
    "compose.json",
    "repository.bundle",
    "images.tar.gz",
    "application.tar.gz",
    "host-settings.tar.gz",
    "postgres_data.tar.gz",
    "redis_data.tar.gz",
    "restore-server.sh",
    "server-transfer-common.sh",
    "server-transfer.py",
    "server-transfer-tests.sh",
    "server-settings.txt",
}


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def config_valid(config, root):
    """Refuse layouts the migration cannot preserve rather than guessing."""
    root = Path(root).resolve()
    services = config["services"]
    if (
        not READERS
        | {"cloudflared", "dispatcher", "data-ingestor", "prediction-worker", "beat"}
        <= services.keys()
    ):
        raise ValueError("Required production services are missing.")
    if set(services) - SERVICES:
        raise ValueError(
            "Unsupported services in the production Compose configuration."
        )
    for service in services.values():
        if (
            service.get("ports")
            or service.get("network_mode")
            or service.get("privileged")
        ):
            raise ValueError(
                "Public ports or privileged services require a separate migration review."
            )
        if service.get("devices") or service.get("secrets") or service.get("configs"):
            raise ValueError("External devices, secrets, or configs are not supported.")
        for mount in service.get("volumes", []):
            if mount["type"] == "bind":
                source = Path(mount["source"])
                if not source.resolve().is_relative_to(root) or source.is_symlink():
                    raise ValueError(
                        "A bind mount is outside the repository or is a symbolic link."
                    )
                relative = source.resolve().relative_to(root).as_posix()
                parts = PurePosixPath(relative).parts
                if not parts or parts[0] not in {
                    "database",
                    "infrastructure",
                    ".local",
                    "model-artifacts",
                    "bootstrap-snapshots",
                }:
                    raise ValueError(
                        "Unsupported bind mount; include its data explicitly before migrating."
                    )
            elif mount["type"] != "volume":
                raise ValueError(
                    "Only local bind mounts and named volumes are supported."
                )
    for logical, volume in config.get("volumes", {}).items():
        if (
            logical not in {"postgres_data", "redis_data"}
            or volume.get("external")
            or volume.get("driver_opts")
        ):
            raise ValueError("Unsupported database volume configuration.")
    if any(
        n.get("external") or n.get("driver_opts")
        for n in config.get("networks", {}).values()
    ):
        raise ValueError("External networks require a separate migration review.")


def inventory(config, root):
    config_valid(config, root)
    containers = json.loads(
        docker(
            "inspect",
            *docker(
                "ps",
                "-aq",
                "--filter",
                "label=com.docker.compose.project=infrastructure",
            ).splitlines(),
        )
    )
    services = {}
    images = {}
    size = 0
    for container in containers:
        service = container["Config"]["Labels"]["com.docker.compose.service"]
        if service in config["services"] and container["State"]["Running"]:
            if container["Config"]["Image"] != config["services"][service]["image"]:
                raise ValueError(
                    "Running images differ from the saved Compose settings."
                )
            if service in {"postgres", "redis"}:
                logical = "postgres_data" if service == "postgres" else "redis_data"
                destination = (
                    "/var/lib/postgresql/data" if service == "postgres" else "/data"
                )
                actual = next(
                    (
                        m.get("Name")
                        for m in container["Mounts"]
                        if m["Destination"] == destination
                    ),
                    None,
                )
                if actual != config["volumes"][logical]["name"]:
                    raise ValueError(
                        "The live database mount differs from the configured volume."
                    )
        if container["State"]["Running"]:
            services[service] = services.get(service, 0) + 1
        tag = container["Config"]["Image"]
        image = json.loads(docker("image", "inspect", tag))[0]
        if image["Id"] != container["Image"]:
            raise ValueError(
                "A container's image tag changed. Resolve the image mismatch first."
            )
        if tag not in images:
            size += image["Size"]
        images[tag] = image["Id"]
    for name in (
        "postgres",
        "redis",
        "dispatcher",
        "data-ingestor",
        "backend-api",
        "bulletin",
        "traefik",
        "cloudflared",
    ):
        if not services.get(name):
            raise ValueError(f"{name} must be running before the final backup.")
    for service in config["services"].values():
        tag = service["image"]
        image = json.loads(docker("image", "inspect", tag))[0]
        if tag not in images:
            size += image["Size"]
        images[tag] = image["Id"]
    volumes = {}
    for logical in ("postgres_data", "redis_data", "pgadmin_data"):
        name = f"infrastructure_{logical}"
        if logical in config.get("volumes", {}):
            name = config["volumes"][logical]["name"]
        result = subprocess.run(
            ["docker", "volume", "inspect", name],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            if logical == "pgadmin_data":
                continue
            raise ValueError(f"Missing production volume: {logical}.")
        mountpoint = json.loads(result.stdout)[0]["Mountpoint"]
        size += int(
            subprocess.check_output(["du", "-sb", mountpoint], text=True).split()[0]
        )
        volumes[logical] = name
    for name in (
        "model-artifacts",
        "bootstrap-snapshots",
        ".local",
        "datasets",
        "data",
    ):
        path = Path(root) / name
        if path.exists():
            size += int(
                subprocess.check_output(["du", "-sb", str(path)], text=True).split()[0]
            )
    sha = subprocess.check_output(
        ["git", "-c", f"safe.directory={root}", "-C", root, "rev-parse", "HEAD"],
        text=True,
    ).strip()
    for name, service in config["services"].items():
        if name not in {"postgres", "redis", "traefik", "cloudflared"} and not service[
            "image"
        ].endswith(f":{sha}"):
            raise ValueError(
                "Application image tags must match the checked-out release SHA. Complete deployment before backup."
            )
    return {
        "format": 1,
        "id": str(uuid.uuid4()),
        "architecture": platform.machine(),
        "repository": root,
        "created_at": datetime.now(UTC).isoformat(),
        "sha": sha,
        "images": images,
        "volumes": volumes,
        "running": services,
        "required_bytes": size * 2 + 6 * 1024**3,
    }


def space(path, needed):
    path = Path(path)
    while not path.exists():
        path = path.parent
    if shutil.disk_usage(path).free < int(needed):
        raise ValueError(
            "Insufficient disk space, including space for extracted images and data."
        )


def resources(project):
    for kind, listing in (
        ("container", ["ps", "-aq"]),
        ("volume", ["volume", "ls", "-q"]),
        ("network", ["network", "ls", "-q"]),
    ):
        ids = docker(
            *listing, "--filter", f"label=com.docker.compose.project={project}"
        ).splitlines()
        for identifier in ids:
            yield kind, identifier, json.loads(docker(kind, "inspect", identifier))[0]


def empty_project(project):
    if list(resources(project)):
        raise ValueError(
            f"Existing {project} resources found. Refusing to overwrite or reuse them."
        )
    for kind, args in (
        ("volume", ["volume", "ls", "--format", "{{.Name}}"]),
        ("container", ["ps", "-a", "--format", "{{.Names}}"]),
        ("network", ["network", "ls", "--format", "{{.Name}}"]),
    ):
        if any(
            re.match(rf"^{re.escape(project)}[_-]", name)
            for name in docker(*args).splitlines()
        ):
            raise ValueError(
                f"Existing {project} {kind} found, including unlabelled resources."
            )


def fresh_host():
    for path in ("/srv/quakestrikeph", "/etc/quakestrike-backup"):
        if os.path.lexists(path):
            raise ValueError(f"{path} already exists. Installation is refused.")
    for project in ("infrastructure", "quakestrikeph"):
        empty_project(project)


def safe_members(archive):
    """Do not let tar escape an extraction root or create device files."""
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unsafe archive path in {Path(archive).name}.")
            if not (member.isfile() or member.isdir()):
                raise ValueError(
                    f"Links or special files in {Path(archive).name} are not supported."
                )


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def seal(directory):
    directory = Path(directory)
    lines = []
    for path in sorted(directory.iterdir()):
        if path.name != "SHA256SUMS":
            if not path.is_file() or path.is_symlink():
                raise ValueError("The package may contain only regular files.")
            lines.append(f"{checksum(path)}  {path.name}\n")
    (directory / "SHA256SUMS").write_text("".join(lines))


def verify(directory):
    directory = Path(directory)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ValueError(
            "The backup directory must be private (chmod 700) and cannot be a symbolic link."
        )
    expected = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if not match or match[2] in expected:
            raise ValueError("Invalid or duplicate checksum entry.")
        expected[match[2]] = match[1]
    if not FILES <= expected.keys() or set(expected) - FILES - {"pgadmin_data.tar.gz"}:
        raise ValueError("The package file list is incomplete or unsupported.")
    if {p.name for p in directory.iterdir()} != set(expected) | {"SHA256SUMS"}:
        raise ValueError("Unlisted files are present in the package.")
    for name, digest in expected.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or checksum(path) != digest:
            raise ValueError(f"Checksum failed: {name}.")
    manifest = read_json(directory / "manifest.json")
    if manifest["format"] != 1 or not re.fullmatch(r"[0-9a-f]{40}", manifest["sha"]):
        raise ValueError("Unsupported manifest or invalid release SHA.")
    uuid.UUID(manifest["id"])
    config_valid(read_json(directory / "compose.json"), manifest["repository"])
    for name in (
        "application.tar.gz",
        "host-settings.tar.gz",
        "postgres_data.tar.gz",
        "redis_data.tar.gz",
    ):
        safe_members(directory / name)
    if (directory / "pgadmin_data.tar.gz").exists():
        safe_members(directory / "pgadmin_data.tar.gz")
    with tarfile.open(directory / "application.tar.gz") as stream:
        names = {m.name.removeprefix("./").rstrip("/") for m in stream}
        if (
            ".env" not in names
            or "bootstrap-snapshots/bootstrap-readiness.json" not in names
        ):
            raise ValueError(
                "Application secrets or bootstrap readiness evidence are missing."
            )
    with tarfile.open(directory / "host-settings.tar.gz") as stream:
        names = {m.name.removeprefix("./") for m in stream}
        for name in ("config", "credentials", "restic-password"):
            if f"etc/quakestrike-backup/{name}" not in names:
                raise ValueError("Backup recovery credentials are missing.")
    return manifest


def restore_config(package, destination, rehearsal, owner):
    package, destination = Path(package), Path(destination)
    manifest = read_json(package / "manifest.json")
    config = copy.deepcopy(read_json(package / "compose.json"))
    project = REHEARSAL if rehearsal else "infrastructure"
    config["name"] = project
    for name in list(config["services"]):
        if rehearsal and name not in READERS:
            del config["services"][name]
            continue
        service = config["services"][name]
        for key in ("build", "profiles", "container_name", "develop", "env_file"):
            service.pop(key, None)
        service["labels"] = {LABEL: owner}
        service["pull_policy"] = "never"
        if rehearsal:
            service["restart"] = "no"
        for mount in service.get("volumes", []):
            if mount["type"] == "bind":
                relative = Path(mount["source"]).relative_to(manifest["repository"])
                mount["source"] = str(destination / relative)
        environment = service.setdefault("environment", {})
        for key in (
            "ALERT_RESOLUTION_ENABLED",
            "ALERT_DELIVERY_ENABLED",
            "ALERT_TEST_CONSUMER_ENABLED",
        ):
            if key in environment:
                environment[key] = "false"
        environment["ALERT_TEST_REDIS_URL"] = ""
        if rehearsal:
            for key in list(environment):
                if key.startswith(
                    ("CLERK_", "PUBLIC_CLERK_", "BREVO_", "IPROG_", "ALERT_TEST_")
                ):
                    environment[key] = ""
            if name == "bulletin":
                environment["API_TARGET"] = "http://backend-api:3000"
        if name == "release-init":
            service["profiles"] = ["init"]
    for logical, volume in config.get("volumes", {}).items():
        volume["name"] = f"{project}_{logical}"
        volume["labels"] = {LABEL: owner}
    for logical, network in config.get("networks", {}).items():
        network["name"] = f"{project}_{logical}"
        network["labels"] = {LABEL: owner}
        if rehearsal:
            network["internal"] = True
    return config


def owned_resources(project, owner):
    if project not in (REHEARSAL, "quakestrike-data-ingestion-test"):
        raise ValueError("Cleanup is restricted to disposable projects.")
    found = list(resources(project))
    for kind, _, data in found:
        labels = (
            data.get("Config", {}).get("Labels", {})
            if kind == "container"
            else data.get("Labels", {})
        )
        if labels.get(LABEL) != owner:
            raise ValueError("Cleanup refused: a resource has a different owner label.")
    return found


def cleanup(project, owner):
    found = owned_resources(project, owner)
    for kind in ("container", "network", "volume"):
        for resource_kind, identifier, _ in found:
            if resource_kind == kind:
                subprocess.run(
                    [
                        "docker",
                        kind,
                        "rm",
                        *(["-f"] if kind == "container" else []),
                        identifier,
                    ],
                    check=True,
                )


def check_junit(path):
    import xml.etree.ElementTree as ET

    cases = list(ET.parse(path).iter("testcase"))
    if not cases:
        raise ValueError("No tests ran.")
    for case in cases:
        if case.find("failure") is not None or case.find("error") is not None:
            raise ValueError("A required test failed.")
        if case.find("skipped") is not None:
            raise ValueError(f"Unexpected test skip: {case.attrib['name']}.")


def main():
    command, *args = sys.argv[1:]
    if command == "validate-config":
        config_valid(json.load(sys.stdin), args[0])
    elif command == "fresh-host":
        fresh_host()
    elif command == "empty-project":
        empty_project(args[0])
    elif command == "seal":
        seal(args[0])
    elif command == "verify":
        verify(args[0])
    elif command == "get":
        value = read_json(Path(args[0]) / "manifest.json")[args[1]]
        print(value if not isinstance(value, (dict, list)) else json.dumps(value))
    elif command == "uuid":
        print(uuid.uuid4())
    elif command == "config":
        write_json(
            args[4], restore_config(args[0], args[1], args[2] == "rehearsal", args[3])
        )
    elif command == "volume-name":
        print(read_json(args[0])["volumes"][args[1]]["name"])
    elif command == "image":
        print(read_json(args[0])["services"][args[1]]["image"])
    elif command == "cleanup":
        cleanup(*args)
    elif command == "check-owner":
        owned_resources(*args)
    elif command == "test-owner":
        owner = read_json(args[0])["services"]["postgres-test"]["labels"][LABEL]
        uuid.UUID(owner)
        print(owner)
    elif command == "junit":
        check_junit(args[0])
    elif command == "tailscale-name":
        status = json.load(sys.stdin)
        if status.get("BackendState") != "Running" or not status.get("Self", {}).get(
            "Online"
        ):
            raise ValueError("Tailscale must be connected before installation.")
        print(status["Self"]["DNSName"].rstrip("."))
    elif command == "safe-archive":
        safe_members(args[0])
    elif command == "inventory":
        manifest = inventory(json.load(sys.stdin), args[0])
        space(args[1], manifest["required_bytes"])
        if len(args) == 3:
            write_json(args[2], manifest)
    elif command == "space":
        space(args[0], args[1])
    elif command == "architecture":
        if (
            read_json(Path(args[0]) / "manifest.json")["architecture"]
            != platform.machine()
        ):
            raise ValueError("The source and destination CPU architectures differ.")
    elif command == "image-conflicts":
        for tag, expected in read_json(Path(args[0]) / "manifest.json")[
            "images"
        ].items():
            result = subprocess.run(
                ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip() != expected:
                raise ValueError(
                    "A saved image tag conflicts with an existing image. Loading is refused."
                )
    elif command == "event-count":
        manifest = read_json(Path(args[0]) / "manifest.json")
        manifest["event_count"] = int(args[1])
        manifest["data_stopped_at"] = datetime.now(UTC).isoformat()
        write_json(Path(args[0]) / "manifest.json", manifest)
    else:
        raise ValueError("Unknown transfer helper operation.")


if __name__ == "__main__":
    try:
        main()
    except (
        ValueError,
        KeyError,
        OSError,
        tarfile.TarError,
        subprocess.CalledProcessError,
    ) as error:
        # Subprocess errors can contain command arguments. Do not echo them.
        message = (
            "A required Docker command failed."
            if isinstance(error, subprocess.CalledProcessError)
            else str(error)
        )
        print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(1)
