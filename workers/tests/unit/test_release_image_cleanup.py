import importlib.util
import json
import subprocess

import pytest

CURRENT = "b" * 40
PREVIOUS = "a" * 40
OLDER = "0" * 40


@pytest.fixture
def cleanup_case(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "cleanup_images", "infrastructure/scripts/cleanup-release-images.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    env = tmp_path / ".env"
    backups = tmp_path / "backups"
    backups.mkdir()

    def tags(sha):
        return "".join(f"{key}={sha}\n" for key in sorted(set(module.IMAGE_TAGS.values())))

    env.write_text(tags(CURRENT))
    (backups / "env.before-release.1").write_text(tags(PREVIOUS))
    images = [
        {"Repository": repo, "Tag": sha, "ID": f"{repo}-{sha}"}
        for repo in module.IMAGE_TAGS
        for sha in (CURRENT, PREVIOUS, OLDER)
    ]
    commands = []
    used = set()

    def docker(*args):
        commands.append(args)
        if args[:2] == ("image", "ls"):
            return "\n".join(json.dumps(row) for row in images)
        if args[:2] == ("container", "ls"):
            return "\n".join(f"container-{n}" for n in range(len(used)))
        if args[:2] == ("container", "inspect"):
            return json.dumps([{"Image": image} for image in used])
        return ""

    monkeypatch.setattr(module, "docker", docker)
    return module, env, backups, images, commands, used, tags


def test_cleanup_keeps_rollback_container_images_and_unrelated_repositories(cleanup_case):
    module, env, backups, images, commands, used, tags = cleanup_case
    # A same-SHA retry still retains the last distinct release.
    (backups / "env.before-release.2").write_text(tags(CURRENT))
    used.add(f"quakestrike-workers-{OLDER}")  # Includes stopped containers.
    images.extend(
        [
            {"Repository": "postgres", "Tag": OLDER, "ID": "postgres"},
            {"Repository": "quakestrike-alert-testing", "Tag": OLDER, "ID": "private"},
            {"Repository": "quakestrike-workers", "Tag": "local", "ID": "local"},
            {
                "Repository": "quakestrike-workers",
                "Tag": "c" * 40,
                "ID": f"quakestrike-workers-{PREVIOUS}",
            },
        ]
    )
    module.cleanup(env, CURRENT, backups)
    assert commands.count(("builder", "prune", "--all", "--force")) == 1
    assert [command for command in commands if command[:2] == ("image", "rm")] == [
        ("image", "rm", f"{repo}:{OLDER}")
        for repo in module.IMAGE_TAGS
        if repo != "quakestrike-workers"
    ]


@pytest.mark.parametrize(
    "problem", ["history", "rollback", "prediction", "tags", "duplicate", "same-sha-only"]
)
def test_invalid_retention_evidence_prevents_all_deletions(cleanup_case, problem):
    module, env, backups, images, commands, _used, _tags = cleanup_case
    if problem == "history":
        (backups / "env.before-release.1").unlink()
    elif problem in ("rollback", "prediction"):
        repo = "quakestrike-workers" if problem == "rollback" else "quakestrike-prediction"
        images[:] = [row for row in images if (row["Repository"], row["Tag"]) != (repo, PREVIOUS)]
    elif problem == "tags":
        env.write_text(env.read_text().replace(CURRENT, PREVIOUS))
    elif problem == "duplicate":
        env.write_text(env.read_text() + f"WORKER_IMAGE_TAG={CURRENT}\n")
    else:
        (backups / "env.before-release.1").write_text(env.read_text())
    with pytest.raises(ValueError):
        module.cleanup(env, CURRENT, backups)
    assert not any(command[:2] in (("builder", "prune"), ("image", "rm")) for command in commands)


def test_first_bulletin_rollout_and_disabled_prediction_are_supported(cleanup_case):
    module, env, backups, images, _commands, _used, tags = cleanup_case
    (backups / "env.before-release.1").write_text(
        tags(PREVIOUS).replace(f"BULLETIN_IMAGE_TAG={PREVIOUS}\n", "")
    )
    images[:] = [
        row
        for row in images
        if row["Repository"] != "quakestrike-prediction"
        and (row["Repository"], row["Tag"]) != ("quakestrike-bulletin", PREVIOUS)
    ]
    module.cleanup(env, CURRENT, backups)


def test_failed_cache_prune_stops_before_image_removal(cleanup_case, monkeypatch):
    module, env, backups, _images, commands, _used, _tags = cleanup_case
    original = module.docker

    def fail_prune(*args):
        if args[:2] == ("builder", "prune"):
            raise subprocess.CalledProcessError(1, ["docker", *args])
        return original(*args)

    monkeypatch.setattr(module, "docker", fail_prune)
    with pytest.raises(subprocess.CalledProcessError):
        module.cleanup(env, CURRENT, backups)
    assert not any(command[:2] == ("image", "rm") for command in commands)


def test_changed_deployment_stops_image_removal(cleanup_case, monkeypatch):
    module, env, backups, _images, commands, _used, tags = cleanup_case
    original = module.docker

    def change_tags(*args):
        if args[:2] == ("builder", "prune"):
            env.write_text(tags("c" * 40))
        return original(*args)

    monkeypatch.setattr(module, "docker", change_tags)
    with pytest.raises(ValueError, match="changed"):
        module.cleanup(env, CURRENT, backups)
    assert not any(command[:2] == ("image", "rm") for command in commands)


def test_container_created_during_prune_is_protected(cleanup_case, monkeypatch):
    module, env, backups, images, commands, used, _tags = cleanup_case
    original = module.docker

    def start_container(*args):
        if args[:2] == ("builder", "prune"):
            used.update(row["ID"] for row in images if row["Tag"] == OLDER)
        return original(*args)

    monkeypatch.setattr(module, "docker", start_container)
    module.cleanup(env, CURRENT, backups)
    assert not any(command[:2] == ("image", "rm") for command in commands)
