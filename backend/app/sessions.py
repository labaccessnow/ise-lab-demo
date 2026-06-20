"""Time-boxed booking session tokens (booking handoff, proj-demo-booking Phase 2).

A booked self-service slot mints one of these (via the Cal.com webhook); it grants
a visitor the portal for the slot window, then expires. File-backed so it survives
a restart. The token is an opaque random id — it holds no secret and carries no
privilege beyond `role=visitor` for one lab until it expires.
"""
import json
import os
import time
import uuid
from threading import Lock

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sessions.json")
_lock = Lock()


def _load() -> dict:
    try:
        with open(_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(d: dict) -> None:
    tmp = _PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, _PATH)


def _prune(d: dict) -> dict:
    now = time.time()
    return {k: v for k, v in d.items() if v.get("expires_at", 0) > now}


def mint(lab_id: str, email: str, expires_at: float) -> str:
    """Create a session token valid until expires_at (unix seconds)."""
    tok = "booking_" + uuid.uuid4().hex
    with _lock:
        d = _prune(_load())
        d[tok] = {
            "lab_id": lab_id, "email": email,
            "expires_at": float(expires_at), "created": time.time(),
        }
        _save(d)
    return tok


def validate(tok: str | None) -> dict | None:
    """Return the session dict if tok is a live booking token, else None."""
    if not tok or not tok.startswith("booking_"):
        return None
    with _lock:
        s = _load().get(tok)
    if not s or time.time() > s.get("expires_at", 0):
        return None
    return s
