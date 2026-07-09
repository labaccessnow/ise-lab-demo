"""Single-tenant hand-off.

The enclave is golden-reset for each NEW occupant, so a visitor never inherits the
previous person's lab — while the SAME user resumes their own (no reset), per the
booking rule. We track which identity the enclave currently belongs to (``owner``)
and whether a prepare-reset is in flight (``preparing``). The reset itself is the
existing ``actions._reset`` (rollback + health-verify + trip maintenance on fail).
"""
import json
import os
import time
from threading import Lock

from . import actions
from .config import RESET_HANDOFF_BUDGET_S

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tenancy.json")
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


def _norm(e) -> str:
    return (e or "").strip().lower()


def status_for(email) -> dict:
    """Is the enclave ready for this identity? ``ready`` = it's already prepared
    for them and no reset is in flight. Drives the portal's 'preparing' screen."""
    me = _norm(email)
    with _lock:
        d = _load()
    owner = _norm(d.get("owner"))
    preparing = bool(d.get("preparing"))
    return {"owner_is_me": bool(me and owner == me),
            "preparing": preparing,
            "ready": bool(me and owner == me and not preparing)}


def claim_preparing(email) -> bool:
    """Atomically decide whether THIS occupant needs a fresh enclave and, if so,
    reserve the prepare (True → caller runs the reset). False when the lab is
    already theirs, a prepare is already running, or the lab is in maintenance —
    never auto-retry into a broken lab (that would be a reset-storm; an admin
    clears maintenance first)."""
    me = _norm(email)
    if not me or actions.maintenance_on():
        return False
    with _lock:
        d = _load()
        if d.get("preparing"):
            return False
        if _norm(d.get("owner")) == me:
            return False
        d["preparing"] = True
        d["preparing_for"] = me
        d["preparing_at"] = time.time()
        _save(d)
    return True


def run_prepare(email, px) -> bool:
    """Golden-reset the enclave for ``email``, then record them as owner. ``_reset``
    trips maintenance + raises on failure; we only clear the preparing flag so the
    portal falls through to the maintenance state (and claim_preparing then refuses
    to retry until an admin clears it)."""
    me = _norm(email)
    ok = False
    try:
        res = actions._reset(px, {}, budget=RESET_HANDOFF_BUDGET_S)
        ok = isinstance(res, dict) and res.get("health") == "ok"
    except Exception as e:
        print(f"[tenancy] prepare reset failed for {me}: {type(e).__name__}")
    with _lock:
        d = _load()
        if ok:
            d["owner"] = me
            d["prepared_at"] = time.time()
        d["preparing"] = False
        d.pop("preparing_for", None)
        _save(d)
    print(f"[tenancy] prepared enclave for {me}: {'ok' if ok else 'FAILED'}")
    return ok


def mark_owner(email) -> None:
    """A manual reset by the current occupant keeps the lab theirs — they just
    re-baselined their own session, so no hand-off reset is owed."""
    me = _norm(email)
    if not me:
        return
    with _lock:
        d = _load()
        d["owner"] = me
        d["prepared_at"] = time.time()
        _save(d)
