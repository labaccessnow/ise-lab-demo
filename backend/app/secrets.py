"""Decrypt the project SOPS store with the project age key.

Secrets live ONLY on this Tier-2 host. Callers must never log the returned values;
the API layer scrubs them from output.
"""
import json
import os
import subprocess

from .config import AGE_KEY, SECRETS_SOPS, SOPS_BIN

_cache = None


def load_secrets(refresh: bool = False) -> dict:
    global _cache
    if _cache is not None and not refresh:
        return _cache
    env = dict(os.environ, SOPS_AGE_KEY_FILE=AGE_KEY)
    out = subprocess.run(
        [SOPS_BIN, "-d", SECRETS_SOPS],
        capture_output=True, text=True, env=env, check=True,
    ).stdout
    _cache = json.loads(out)
    return _cache
