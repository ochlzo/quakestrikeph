"""Portable path syntax shared by package creation and bundle verification."""

from __future__ import annotations

from pathlib import PurePosixPath

_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def safe_relative_path(value: object) -> PurePosixPath:
    """Reject aliases that resolve differently on Windows and Linux."""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("Unsafe relative path.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(
        part in ("", ".", "..")
        or part.strip() != part
        or part.endswith(".")
        or part.split(".")[0].casefold() in _RESERVED
        for part in value.split("/")
    ):
        raise ValueError("Unsafe relative path.")
    return path
