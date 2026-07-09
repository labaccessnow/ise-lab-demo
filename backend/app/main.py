"""Tier-2 FastAPI backend.

Exposes ONLY the allowlisted action registry to the portal, behind a role check
and guardrails. Demo visitors never reach this directly (network isolation); the
Tier-1 portal authenticates them and forwards the resolved role.

Auth here is intentionally a stub (X-Role / X-Session headers set by the trusted
portal). Real visitor/admin auth (Authelia + demo-session token) lands in Phase 6;
this service must only ever be reachable from the portal, never the internet.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, Header, HTTPException

from . import authentik_sync, calcom, catalog, guardrails, sessions
from .actions import ACTIONS, LabUnavailable
from .actions import maintenance_on as actions_maintenance_on
from .devices import DeviceError
from .proxmox import Proxmox, ProxmoxError
from .webhook import router as webhook_router


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Background reconciler: keeps the Authentik lab-active group equal to
    # "bookings running right now", so the group-gated desktop opens at slot
    # start and closes at slot end with no operator action.
    async def loop():
        while True:
            try:
                res = await asyncio.to_thread(
                    authentik_sync.reconcile, sessions.active_emails())
                if res.get("added") or res.get("removed") or res.get("no_account"):
                    print(f"[lab-active] {res}")
            except Exception as e:
                print(f"[lab-active] sync failed: {e}")
            await asyncio.sleep(60)
    task = asyncio.create_task(loop())
    yield
    task.cancel()


app = FastAPI(title="ise-lab-demo backend", docs_url=None, redoc_url=None,
              lifespan=_lifespan)
app.include_router(webhook_router)

_px: Proxmox | None = None


def px() -> Proxmox:
    global _px
    if _px is None:
        _px = Proxmox()
    return _px


_ROLES = {"visitor": 0, "admin": 1}


def _authorized(have: str, need: str) -> bool:
    return _ROLES.get(have, -1) >= _ROLES.get(need, 99)


@app.get("/healthz")
def healthz():
    return {"ok": True, "running": guardrails.current()["action"]}


@app.get("/api/session/{token}")
def session_info(token: str):
    """Let the portal validate a booking session token (presence + expiry)."""
    s = sessions.validate(token)
    if not s:
        raise HTTPException(404, "invalid or expired session")
    return {"valid": True, "lab": s["lab_id"], "expires_at": s["expires_at"]}


@app.post("/api/session/claim")
def session_claim(payload: dict | None = Body(default=None),
                  x_identity_email: str = Header(None)):
    """Redeem a booking token against the edge-verified identity (forwarded by the
    trusted portal as X-Identity-Email). Binds the token single-use to that identity
    and returns a fresh server_sid the portal sets as an httponly cookie — a forwarded
    ?session= link is useless to anyone else. The booking token never returns to the
    client. 403 on wrong identity / already-claimed-by-other / expired."""
    token = (payload or {}).get("token")
    res = sessions.claim(token, x_identity_email)
    if not res:
        raise HTTPException(403, "session could not be claimed (wrong identity, already in use, or expired)")
    return res


@app.get("/api/booking-state")
def booking_state(x_identity_email: str = Header(None)):
    """The verified identity's booking picture (active / upcoming / none) PLUS
    who holds the single-tenant lab right now. The lab is one shared enclave, so
    only the current occupant may drive it; everyone else (admins included) sees
    it as busy. Never includes the token."""
    me = (x_identity_email or "").strip().lower()
    st = sessions.state_for_email(me)
    occ = sessions.occupant()
    st["occupied"] = bool(occ)
    st["occupant_is_me"] = bool(occ and occ["email"] == me)
    st["occupant_until"] = occ["until"] if occ else None
    return st


@app.post("/api/book")
def book_slot(payload: dict | None = Body(default=None),
              x_identity_email: str = Header(None)):
    """Book the lab for the EDGE-VERIFIED identity. The attendee email is taken
    only from X-Identity-Email (set by the trusted portal from the Authentik
    subrequest) — the client may pass a display name and a start time, never the
    email. This is what makes the reservation identity-bound: you cannot book the
    lab as anyone but yourself. Cal.com then fires its webhook, which mints the
    slot-bound session exactly as for any booking."""
    email = (x_identity_email or "").strip().lower()
    if not email:
        raise HTTPException(401, "sign in to book")
    # Defense in depth: the edge already authenticated, but confirm the account is
    # active (email-verified) before consuming a slot / mailing a link.
    if authentik_sync.is_active_account(email) is False:
        raise HTTPException(403, "account is not an active lab member")
    start = (payload or {}).get("start") or calcom.next_slot_iso()
    name = (payload or {}).get("name") or ""
    try:
        res = calcom.book(email, name, start)
    except calcom.BookingError as e:
        if e.conflict:
            raise HTTPException(409, "That time isn't available — pick another slot.")
        raise HTTPException(502, "Booking service is unavailable right now.")
    return {"ok": True, **res}


@app.get("/api/actions")
def list_actions(x_role: str = Header("visitor")):
    return {
        aid: {"role": a.role, "mutating": a.mutating, "summary": a.summary}
        for aid, a in ACTIONS.items()
        if _authorized(x_role, a.role)
    }


@app.post("/api/action/{action_id}")
def run_action(action_id: str,
               payload: dict | None = Body(default=None),
               x_role: str = Header("visitor"),
               x_session: str = Header("anon"),
               x_client_ip: str = Header(None),
               x_identity_email: str = Header(None),
               x_booking_exempt: str = Header("0")):
    act = ACTIONS.get(action_id)
    if act is None:
        raise HTTPException(404, "unknown action")
    if not _authorized(x_role, act.role):
        raise HTTPException(403, f"action requires role '{act.role}'")
    # While the lab is offline (a reset failed health-check), don't let a visitor
    # drive any action against the half-broken lab — except lab.status, which feeds
    # the maintenance banner. Admin recovery actions (clear_maintenance) stay open.
    if act.role == "visitor" and action_id != "lab.status" and actions_maintenance_on():
        raise HTTPException(503, "Lab is temporarily offline for maintenance. Please try again later.")
    # The enclave is ONE shared set of VMs — strictly single-tenant. Any MUTATING
    # lab action (reset, API writes) requires you to be the CURRENT OCCUPANT: the
    # single identity whose booked slot is live now. Admins/testers are NOT exempt
    # (they book too) so two people can never drive the same enclave at once.
    # Admin-ROLE recovery actions (e.g. clear_maintenance) are gated by role above,
    # not occupancy, so an operator can always recover a broken lab.
    if act.mutating and act.role != "admin":
        me = (x_identity_email or "").strip().lower()
        occ = sessions.occupant()
        if not (occ and occ["email"] == me):
            if occ:
                raise HTTPException(409, "The lab is in use by another session right now — it's one visitor at a time.")
            raise HTTPException(403, "The lab is reserved one session at a time — book your slot to take the controls.")
    # Rate-limit ONLY the expensive mutating actions (reset/create), keyed on the
    # real client IP the edge forwards (X-Client-IP) — NOT a client-chosen session
    # id, which a script trivially rotates to bypass the cap. Cheap reads
    # (lab.status etc.) are never limited, so an engaged visitor never hits the wall.
    if act.mutating:
        try:
            guardrails.rate_check(x_client_ip or x_session)
        except guardrails.RateLimited as e:
            raise HTTPException(429, str(e))
        try:
            guardrails.acquire(action_id)
        except guardrails.Busy as e:
            raise HTTPException(409, str(e))
    try:
        return {"action": action_id, "result": act.fn(px(), payload or {})}
    except LabUnavailable as e:
        raise HTTPException(503, str(e))
    except (ProxmoxError, DeviceError) as e:
        raise HTTPException(502, str(e))
    finally:
        if act.mutating:
            guardrails.release()


@app.get("/api/catalog")
def api_catalog(x_role: str = Header("visitor")):
    """The API playground catalog the visitor's role may run (id, params, etc.)."""
    return [op for op in catalog.public() if _authorized(x_role, op["role"])]
