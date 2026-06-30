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


def _norm(email: str | None) -> str:
    return (email or "").strip().lower()


def claim(tok: str | None, identity_email: str | None) -> dict | None:
    """Redeem a booking token against the edge-verified identity.

    Binds the token to the booker's email and hands back a fresh server-minted
    ``server_sid`` (the client never sees the booking token again — it gets an
    httponly sid cookie). This makes a forwarded ``?session=`` link useless to a
    different person and the token effectively single-use:

    - token missing/expired -> None
    - a DIFFERENT identity than the one who first claimed it -> None (forward-proof)
    - first claim by an identity that doesn't match the booking email -> None
    - same identity re-claiming (refresh / reconnect / new tab) -> a NEW server_sid,
      which invalidates the previous one (kick-old: one live session per token)
    """
    if not tok or not tok.startswith("booking_"):
        return None
    who = _norm(identity_email)
    if not who:
        return None  # no verified identity -> cannot bind
    with _lock:
        d = _prune(_load())
        s = d.get(tok)
        if not s or time.time() > s.get("expires_at", 0):
            return None
        claimed_by = s.get("claimed_by")
        if claimed_by:
            if claimed_by != who:
                return None  # someone else's claimed link
        else:
            booked = _norm(s.get("email"))
            if booked and booked != who:
                return None  # forwarded to a different person before first claim
            s["claimed_by"] = who
        s["server_sid"] = "sid_" + uuid.uuid4().hex   # kick-old: replaces any prior sid
        s["claimed_at"] = time.time()
        d[tok] = s
        _save(d)
    return {"server_sid": s["server_sid"], "lab_id": s["lab_id"], "expires_at": s["expires_at"]}


def validate_sid(server_sid: str | None) -> dict | None:
    """Return the session for a live, claimed server_sid (the cookie the client
    actually carries after claiming), else None."""
    if not server_sid or not server_sid.startswith("sid_"):
        return None
    now = time.time()
    with _lock:
        for s in _load().values():
            if s.get("server_sid") == server_sid and s.get("expires_at", 0) > now:
                return s
    return None
