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

# "Start now" books the next slot boundary (≤5 min out); treat a booking whose
# start is within this grace of now as already active so "now" feels immediate.
# Scheduled future bookings just activate this many seconds early — harmless for a
# single-tenant lab that resets at the slot anyway.
_ACTIVE_GRACE_S = 330


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


def mint(lab_id: str, email: str, expires_at: float,
         starts_at: float | None = None, uid: str = "") -> str:
    """Create a session token for a booked slot window.

    ``starts_at`` is the slot start (unix seconds) — before it the booking is
    "upcoming" and grants nothing; omitted means "starts now" (legacy records
    without the field behave the same via ``created``). ``uid`` is the Cal.com
    booking uid so a cancellation/reschedule can find the session it minted.
    """
    tok = "booking_" + uuid.uuid4().hex
    now = time.time()
    with _lock:
        d = _prune(_load())
        d[tok] = {
            "lab_id": lab_id, "email": email, "uid": uid,
            "starts_at": float(starts_at) if starts_at else now,
            "expires_at": float(expires_at), "created": now,
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


def _start_of(s: dict) -> float:
    # Legacy records (pre starts_at) were active from the moment they were minted.
    return s.get("starts_at") or s.get("created") or 0


def _belongs_to(s: dict, who: str) -> bool:
    # A session is "yours" if you booked it or you're the identity that claimed it.
    return bool(who) and who in {_norm(s.get("email")), _norm(s.get("claimed_by"))}


def state_for_email(email: str | None) -> dict:
    """The booking picture for a verified identity: the ACTIVE session if one is
    live now, else the soonest UPCOMING one, else none. Never exposes the token —
    this feeds the portal UI, and the UI must not be able to leak a usable link."""
    who = _norm(email)
    now = time.time()
    best = None
    if who:
        with _lock:
            live = _prune(_load())
        for s in live.values():
            if not _belongs_to(s, who):
                continue
            if _start_of(s) <= now + _ACTIVE_GRACE_S:
                best = ("active", s)
                break
            if best is None or _start_of(s) < _start_of(best[1]):
                best = ("upcoming", s)
    if best is None:
        return {"state": "none"}
    state, s = best
    return {"state": state, "lab_id": s.get("lab_id"),
            "starts_at": _start_of(s), "expires_at": s.get("expires_at")}


def has_active(email: str | None) -> bool:
    """True when the identity's booked window is running right now."""
    return state_for_email(email).get("state") == "active"


def occupant() -> dict | None:
    """The SINGLE identity that currently holds the lab, or None if it's free.

    The enclave is one shared set of VMs (one jumpbox), so it is strictly
    single-tenant: the occupant is the active booking with the earliest start.
    Admins/testers are NOT implicit occupants — everyone books, so no one can
    silently share an occupied lab. If two sessions somehow overlap (grace,
    double-book), the earliest-start one wins and the other must wait."""
    now = time.time()
    with _lock:
        live = _prune(_load())
    active = [s for s in live.values() if _start_of(s) <= now + _ACTIVE_GRACE_S]
    if not active:
        return None
    s = min(active, key=_start_of)
    who = _norm(s.get("claimed_by")) or _norm(s.get("email"))
    if not who:
        return None
    return {"email": who, "until": s.get("expires_at"), "lab_id": s.get("lab_id")}


def active_emails() -> set[str]:
    """Desired membership of the Authentik lab-active group the desktop gate keys
    on — AT MOST the one current occupant, so the streamed desktop can never be
    reached by two people at once."""
    occ = occupant()
    return {occ["email"]} if occ else set()


def drop_uid(uid: str | None) -> int:
    """Remove the session(s) minted for a cancelled booking uid. Returns count."""
    if not uid:
        return 0
    with _lock:
        d = _load()
        doomed = [k for k, v in d.items() if v.get("uid") == uid]
        for k in doomed:
            del d[k]
        if doomed:
            _save(d)
    return len(doomed)


def reschedule_uid(uid: str | None, starts_at: float, expires_at: float,
                   new_uid: str = "") -> bool:
    """Move an existing booking's window (Cal.com reschedule) and re-key it to
    the new booking uid so a later cancel finds it. False if unknown — the
    caller then mints a fresh session instead."""
    if not uid:
        return False
    with _lock:
        d = _load()
        hit = False
        for v in d.values():
            if v.get("uid") == uid:
                v["starts_at"], v["expires_at"] = float(starts_at), float(expires_at)
                v["uid"] = new_uid or v.get("uid")
                hit = True
        if hit:
            _save(d)
    return hit
