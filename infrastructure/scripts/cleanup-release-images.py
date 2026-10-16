"""Remove unused build cache and old release images after a successful deployment."""

import json
import re
import subprocess
import sys
from pathlib import Path

IMAGE_TAGS = {
    "quakestrike-workers": "WORKER_IMAGE_TAG",
    "quakestrike-prediction": "WORKER_IMAGE_TAG",
    "quakestrike-backend": "BACKEND_IMAGE_TAG",
    "quakestrike-bulletin": "BULLETIN_IMAGE_TAG",
}


def release_tags(path: Path) -> dict[str, str]:
    tags = {}
    for line in path.read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator and key in IMAGE_TAGS.values():
            if key in tags or not re.fullmatch(r"[0-9a-f]{40}", value):
                raise ValueError(f"Invalid or duplicate {key}")
            tags[key] = value
    if not {"WORKER_IMAGE_TAG", "BACKEND_IMAGE_TAG"} <= tags.keys():
        raise ValueError("Release tags are missing")
    return tags


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True)


def referenced_images() -> set[str]:
    containers = docker("container", "ls", "--all", "--quiet").split()
    if not containers:
        return set()
    return {
        item["Image"]
        for item in json.loads(docker("container", "inspect", *containers))
    }


def cleanup(path: Path, sha: str, backups: Path) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid release SHA")
    current = release_tags(path)
    if set(current) != set(IMAGE_TAGS.values()) or set(current.values()) != {sha}:
        raise ValueError("Saved tags do not match the successful deployment")

    # Same-SHA workflow retries must not replace the previous distinct release.
    previous = {}
    history = sorted(backups.glob("env.before-release.*"), reverse=True)
    if not history:
        raise ValueError("Release history is missing; retaining all images and cache")
    unresolved = set(current)
    for backup in history:
        tags = release_tags(backup)
        for key in list(unresolved):
            if key not in tags:
                # The first Bulletin rollout has no earlier image.
                unresolved.remove(key)
            elif tags[key] != current[key]:
                previous[key] = tags[key]
                unresolved.remove(key)
        if not unresolved:
            break
    if unresolved:
        raise ValueError(
            "Previous distinct release is unavailable; retaining all images and cache"
        )

    images = [
        json.loads(line)
        for line in docker(
            "image", "ls", "--no-trunc", "--format", "{{json .}}"
        ).splitlines()
    ]
    available = {f"{item['Repository']}:{item['Tag']}" for item in images}
    retained = {
        f"{repo}:{tags[key]}"
        for repo, key in IMAGE_TAGS.items()
        for tags in (current, previous)
        if key in tags
    }
    required = {
        ref for ref in retained if not ref.startswith("quakestrike-prediction:")
    }
    if f"quakestrike-prediction:{sha}" in available:
        required = retained
    if not required <= available:
        raise ValueError(
            "A retained release image is missing; retaining all images and cache"
        )
    protected_ids = {
        item["ID"]
        for item in images
        if f"{item['Repository']}:{item['Tag']}" in retained
    }
    candidates = [
        item
        for item in images
        if item["Repository"] in IMAGE_TAGS
        and re.fullmatch(r"[0-9a-f]{40}", item["Tag"])
        and item["ID"] not in protected_ids
    ]

    print(docker("builder", "prune", "--all", "--force"), end="", flush=True)
    removed = 0
    for item in candidates:
        if release_tags(path) != current:
            raise ValueError("Deployment tags changed during cleanup")
        if item["ID"] in referenced_images():
            continue
        reference = f"{item['Repository']}:{item['Tag']}"
        print(docker("image", "rm", reference), end="", flush=True)
        removed += 1
    print(
        f"Release cleanup removed {removed} old image tags; retained current and previous releases."
    )


if __name__ == "__main__":
    try:
        cleanup(
            Path(sys.argv[1]),
            sys.argv[2],
            Path.home() / ".local/state/quakestrikeph/env-backups",
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Release cleanup failed: {error}", file=sys.stderr)
        sys.exit(1)
