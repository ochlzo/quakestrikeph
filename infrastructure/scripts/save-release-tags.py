"""Save successful image tags atomically without rewriting private settings."""

import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def save_tags(path: Path, sha: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid release SHA")
    original = path.read_bytes()
    text = original.decode("utf-8")
    for name in ("WORKER_IMAGE_TAG", "BACKEND_IMAGE_TAG", "BULLETIN_IMAGE_TAG"):
        pattern = re.compile(rf"^{name}=.*$", re.MULTILINE)
        count = len(pattern.findall(text))
        if count > 1 or (count == 0 and name != "BULLETIN_IMAGE_TAG"):
            raise ValueError(f"Expected one {name}")
        if count:
            text = pattern.sub(f"{name}={sha}", text)
        else:
            text = text.rstrip("\n") + f"\n{name}={sha}\n"
    backups = Path.home() / ".local/state/quakestrikeph/env-backups"
    backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    backups.chmod(0o700)
    backup = backups / datetime.now(UTC).strftime(
        "env.before-release.%Y%m%dT%H%M%S.%fZ"
    )
    with backup.open("xb") as stream:
        backup.chmod(0o600)
        stream.write(original)
    fd, name = tempfile.mkstemp(prefix=".env.release-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.chmod(name, 0o600)
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != original:
            raise RuntimeError("Private environment changed during deployment")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


if __name__ == "__main__":
    save_tags(Path(sys.argv[1]), sys.argv[2])
