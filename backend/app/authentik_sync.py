"""Keep the Authentik ``lab-active`` group equal to "who has a booked session
running RIGHT NOW".

Authentik-gated surfaces that must track the booking window (the streamed
desktop app) bind to this group; booked visitors appear in it at slot start and
vanish at slot end with no operator action. Admin/tester overrides live in
separate groups (lab-admins / lab-approved) that this module NEVER touches — it
only ever adds/removes members of the one group it owns.

Deployment coordinates come from the gitignored .env (placeholders in
.env.example): AUTHENTIK_URL (the lab's own Authentik, reachable from this
Tier-2 host) and AUTHENTIK_LAB_ACTIVE_GROUP (the group's pk/uuid). The API
token lives in the lab SOPS store under ``authentik.api_token`` and must never
be logged.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .secrets import load_secrets

_URL = os.environ.get("AUTHENTIK_URL", "").rstrip("/")
_GROUP = os.environ.get("AUTHENTIK_LAB_ACTIVE_GROUP", "")


class SyncError(RuntimeError):
    pass


def _token() -> str:
    return ((load_secrets() or {}).get("authentik") or {}).get("api_token", "")


def configured() -> bool:
    return bool(_URL and _GROUP and _token())


def _req(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{_URL}/api/v3{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {_token()}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        # Status only — bodies/URLs can carry identifiers we don't want in logs.
        raise SyncError(f"authentik {method} {path.split('?')[0]} -> {e.code}")
    except (urllib.error.URLError, OSError) as e:
        raise SyncError(f"authentik unreachable: {type(e).__name__}")
    return json.loads(raw) if raw else {}


def _norm(email: str | None) -> str:
    return (email or "").strip().lower()


def _members() -> dict[str, int]:
    """Current group membership as normalized-email -> user pk."""
    data = _req("GET", f"/core/users/?groups_by_pk={_GROUP}&page_size=200")
    return {e: u["pk"] for u in data.get("results", []) if (e := _norm(u.get("email")))}


def _find_user(email: str) -> int | None:
    """User pk for an exact (normalized) email, via search + exact match —
    Authentik's search spans username/name/email, so filter the hits."""
    data = _req("GET", f"/core/users/?search={urllib.parse.quote(email)}&page_size=20")
    for u in data.get("results", []):
        if _norm(u.get("email")) == email:
            return u["pk"]
    return None


def is_active_account(email: str) -> bool | None:
    """True if the email maps to an active (verified→activated) Authentik account,
    False if it exists but is inactive, None if unknown/unresolvable. Used by the
    webhook to refuse minting a session for an email that isn't a real member —
    stops a gated-but-forged attendee address from pulling a booking link out of
    our mailer or polluting the lab-active group. Fail-open (None) when Authentik
    can't be reached, so an outage doesn't silently break all bookings."""
    e = _norm(email)
    if not (e and _URL and _token()):
        return None
    try:
        data = _req("GET", f"/core/users/?search={urllib.parse.quote(e)}&page_size=20")
    except SyncError:
        return None
    for u in data.get("results", []):
        if _norm(u.get("email")) == e:
            return bool(u.get("is_active"))
    return False


def reconcile(desired_emails: set[str]) -> dict:
    """Make lab-active membership == desired_emails. Idempotent and self-healing:
    a missed tick or backend restart converges on the next run. Bookings made
    with an email that has no Authentik account (attendee email != SSO email)
    are reported, not fatal — the portal-side access still works via the claimed
    identity; only the group-gated desktop needs the account to match."""
    if not configured():
        return {"skipped": "authentik sync not configured"}
    have = _members()
    added, removed, no_account = [], [], []
    for email in sorted(desired_emails - set(have)):
        pk = _find_user(email)
        if pk is None:
            no_account.append(email)
            continue
        _req("POST", f"/core/groups/{_GROUP}/add_user/", {"pk": pk})
        added.append(email)
    for email in sorted(set(have) - desired_emails):
        _req("POST", f"/core/groups/{_GROUP}/remove_user/", {"pk": have[email]})
        removed.append(email)
    return {"added": added, "removed": removed, "no_account": no_account}
