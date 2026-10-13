"""Stateless preparation authentication; no draft storage or recovery."""

import hashlib
import hmac
import json
import re


def canonical(value):
    # JavaScript serializes whole floats as integers; preserve JSON number semantics.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [canonical(item) for item in value]
    return value


def encode(value):
    return json.dumps(canonical(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


class PreparationSigner:
    def __init__(self, key: str):
        if not isinstance(key, str) or len(key.encode()) < 32:
            raise ValueError("Configure a preparation key of at least 32 bytes.")
        self.key = key.encode()

    def token(self, scenario, inputs):
        reviewed = {key: value for key, value in scenario.items() if key != "preparation_token"}
        return hmac.new(self.key, encode([reviewed, inputs]).encode(), hashlib.sha256).hexdigest()

    def verify(self, scenario, inputs):
        if not isinstance(scenario, dict):
            raise ValueError("Missing preparation.")
        token = scenario.get("preparation_token")
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token):
            raise ValueError("Invalid preparation.")
        try:
            expected = self.token(scenario, inputs)
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise ValueError("Invalid preparation.") from None
        if not hmac.compare_digest(token, expected):
            raise ValueError("Invalid preparation.")
