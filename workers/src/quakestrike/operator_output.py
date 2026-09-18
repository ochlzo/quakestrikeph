"""Bounded JSON output for explicit operator commands."""

from __future__ import annotations

import json


def print_json(value: object) -> None:
    print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
