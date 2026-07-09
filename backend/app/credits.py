"""Per-account credit ledger — lab time the visitor has bought, in minutes.

A Stripe purchase grants minutes (via the webhook); booking spends them once the
lab goes paid. File-backed with an append-only entry list for a simple audit
trail. Grants are idempotent by Stripe reference (session id) so a re-delivered
webhook never double-credits.
"""
import json
import os
import time
from threading import Lock

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "credits.json")
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


def balance(email) -> int:
    """Remaining credit for this account, in minutes."""
    me = _norm(email)
    if not me:
        return 0
    with _lock:
        return int(_load().get(me, {}).get("balance", 0))


def grant(email, minutes, ref="") -> dict:
    """Add `minutes` of credit. Idempotent by `ref` (Stripe session id): a repeat
    delivery with the same ref is ignored. Returns {balance, granted}."""
    me = _norm(email)
    minutes = int(minutes)
    with _lock:
        d = _load()
        acct = d.setdefault(me, {"balance": 0, "entries": []})
        if ref and any(e.get("ref") == ref and e.get("delta", 0) > 0 for e in acct["entries"]):
            return {"balance": int(acct["balance"]), "granted": False}
        acct["balance"] = int(acct["balance"]) + minutes
        acct["entries"].append({"ts": time.time(), "delta": minutes, "ref": ref, "bal": acct["balance"]})
        _save(d)
        return {"balance": acct["balance"], "granted": True}


def spend(email, minutes, ref="") -> bool:
    """Deduct `minutes` if the account has enough. Returns True on success."""
    me = _norm(email)
    minutes = int(minutes)
    with _lock:
        d = _load()
        acct = d.setdefault(me, {"balance": 0, "entries": []})
        if int(acct["balance"]) < minutes:
            return False
        acct["balance"] = int(acct["balance"]) - minutes
        acct["entries"].append({"ts": time.time(), "delta": -minutes, "ref": ref, "bal": acct["balance"]})
        _save(d)
        return True
