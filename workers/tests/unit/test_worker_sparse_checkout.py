import subprocess
from pathlib import Path


def test_sparse_deployment_excludes_bulletin_and_keeps_backend_and_secrets(tmp_path: Path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    for name in (
        "workers/worker.py",
        "apps/backend-api/index.ts",
        "apps/quakestrikeph-bulletin/page.astro",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("first", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "initial")
    first = git("rev-parse", "HEAD")
    (tmp_path / "apps/quakestrikeph-bulletin/page.astro").write_text("second", encoding="utf-8")
    git("commit", "-am", "bulletin update")
    second = git("rev-parse", "HEAD")
    git("switch", "--detach", first)
    (tmp_path / ".env").write_text("test configuration", encoding="utf-8")
    git("sparse-checkout", "set", "--no-cone", "/*", "!/apps/quakestrikeph-bulletin/")
    git("switch", "--detach", second)
    assert not (tmp_path / "apps/quakestrikeph-bulletin").exists()
    assert (tmp_path / "workers/worker.py").exists()
    assert (tmp_path / "apps/backend-api/index.ts").exists()
    assert (tmp_path / ".env").read_text() == "test configuration"
    assert git("status", "--porcelain") == ""
