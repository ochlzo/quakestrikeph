import importlib.util
from pathlib import Path

import pytest


def saver():
    path = Path("infrastructure/scripts/save-release-tags.py")
    spec = importlib.util.spec_from_file_location("release_tags", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tag_save_preserves_secrets_and_keeps_a_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / ".env"
    original = (
        "WORKER_IMAGE_TAG="
        + "a" * 40
        + "\nBACKEND_IMAGE_TAG="
        + "a" * 40
        + "\nPRIVATE_TOKEN='test-only-secret'\nALERT_DELIVERY_ENABLED=false\n"
    )
    path.write_text(original)
    saver().save_tags(path, "b" * 40)
    updated = path.read_text()
    assert "PRIVATE_TOKEN='test-only-secret'\nALERT_DELIVERY_ENABLED=false" in updated
    for name in ("WORKER_IMAGE_TAG", "BACKEND_IMAGE_TAG", "BULLETIN_IMAGE_TAG"):
        assert f"{name}={'b' * 40}" in updated
    backups = list((tmp_path / ".local/state/quakestrikeph/env-backups").iterdir())
    assert len(backups) == 1 and backups[0].read_text() == original
    assert not list(tmp_path.glob(".env.release-*"))


def test_duplicate_tag_leaves_private_environment_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / ".env"
    original = "WORKER_IMAGE_TAG=a\nWORKER_IMAGE_TAG=b\nBACKEND_IMAGE_TAG=c\n"
    path.write_text(original)
    with pytest.raises(ValueError, match="Expected one WORKER_IMAGE_TAG"):
        saver().save_tags(path, "b" * 40)
    assert path.read_text() == original


def test_failed_atomic_replace_keeps_previous_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / ".env"
    original = "WORKER_IMAGE_TAG=a\nBACKEND_IMAGE_TAG=a\nPRIVATE_VALUE=preserved\n"
    path.write_text(original)
    module = saver()

    def fail_replace(_source, _target):
        raise OSError("Test-only replace failure")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="Test-only replace failure"):
        module.save_tags(path, "b" * 40)
    assert path.read_text() == original
    assert not list(tmp_path.glob(".env.release-*"))
