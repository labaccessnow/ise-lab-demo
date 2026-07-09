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

from fastapi import Body, FastAPI, Header, HTTPException, Request

from . import authentik_sync, calcom, catalog, credits, guardrails, sessions, stripe_pay, tenancy
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
                # Auto reset-on-tenant-change: when a NEW occupant holds the lab and
                # the enclave isn't already prepared for them, golden-reset it in the
                # background (single-flight via the preparing flag) so they never
                # inherit the last person's lab. Same user resumes untouched.
                occ = sessions.occupant()
                if occ and tenancy.claim_preparing(occ["email"]):
                    print(f"[tenancy] new occupant {occ['email']} — preparing enclave")
                    asyncio.create_task(
                        asyncio.to_thread(tenancy.run_prepare, occ["email"], px()))
            except Exception as e:
                print(f"[loop] iteration failed: {e}")
            await asyncio.sleep(30)
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
    # Hand-off readiness: the lab controls unlock only once the enclave has been
    # golden-reset for THIS occupant (or resumed for the same user). While that
    # reset runs the portal shows a "preparing your lab" screen.
    ten = tenancy.status_for(me)
    st["lab_ready"] = bool(st["occupant_is_me"] and ten["ready"])
    st["lab_preparing"] = bool(st["occupant_is_me"] and not ten["ready"] and not actions_maintenance_on())
    st["maintenance"] = actions_maintenance_on()
    st["credit_min"] = credits.balance(me)
    return st


@app.post("/api/checkout")
def checkout(payload: dict | None = Body(default=None), x_identity_email: str = Header(None)):
    """Create a Stripe (test-mode) Checkout Session to buy lab hours for the
    verified identity; the portal redirects the buyer to the returned hosted URL."""
    email = (x_identity_email or "").strip().lower()
    if not email:
        raise HTTPException(401, "sign in to buy hours")
    if not stripe_pay.configured():
        raise HTTPException(503, "payments are not configured")
    try:
        hours = int((payload or {}).get("hours") or 1)
    except (TypeError, ValueError):
        hours = 1
    try:
        s = stripe_pay.create_checkout_session(email, hours)
    except stripe_pay.StripeError as e:
        print(f"[stripe] checkout failed: {e}")
        raise HTTPException(502, "couldn't start checkout — try again")
    return {"ok": True, "url": s["url"]}


@app.post("/api/webhook/stripe")
async def stripe_webhook(request: Request):
    """Stripe posts here after a purchase. Verify the signature, then credit the
    buyer's ledger (idempotent by session id). Fast 2xx so Stripe doesn't retry."""
    body = await request.body()
    evt = stripe_pay.verify_event(body, request.headers.get("Stripe-Signature", ""))
    if not evt:
        raise HTTPException(400, "bad signature")
    if evt.get("type") == "checkout.session.completed":
        obj = (evt.get("data") or {}).get("object") or {}
        email = ((obj.get("metadata") or {}).get("email")
                 or obj.get("client_reference_id") or obj.get("customer_email") or "")
        try:
            hours = int((obj.get("metadata") or {}).get("hours") or 0)
        except (TypeError, ValueError):
            hours = 0
        if email and hours > 0:
            res = credits.grant(email, hours * 60, ref=obj.get("id", ""))
            print(f"[stripe] {email} +{hours}h granted={res['granted']} bal={res['balance']}m")
    return {"ok": True}


@app.get("/api/slots")
def slots(date: str = ""):
    """Open/taken slots for a day (event TZ), for the in-portal booking calendar.
    Availability is derived from live sessions (every booking mints one), so the
    visitor sees exactly what's free. Booking still goes through /api/book, which
    is the authority on conflicts."""
    return calcom.day_slots(date, sessions.busy_ranges())


# Hard ceiling the system supports = 24h (hourly steps). The ACTUAL cap is the
# tier's soft cap sent by the portal (X-Booking-Max-Min, currently 8h) — so raising
# paid users to 12h/24h later is a pure portal .env change, no code edit needed.
_ALLOWED_DUR = [60 * h for h in range(1, 25)]  # 1h .. 24h


@app.post("/api/book")
def book_slot(payload: dict | None = Body(default=None),
              x_identity_email: str = Header(None),
              x_booking_max_min: str = Header("60"),
              x_booking_daily_min: str = Header("60")):
    """Book the lab for the EDGE-VERIFIED identity. The attendee email is taken
    ONLY from X-Identity-Email (set by the trusted portal from the Authentik
    subrequest) — the client may pass a display name, start time and requested
    duration, never the email. So a reservation is always identity-bound.

    Duration is tiered: the portal passes the caller's per-session cap
    (X-Booking-Max-Min) and per-day quota (X-Booking-Daily-Min) from their group
    (free 1h, paid/admin 8h + 8h/day). We hold the base slot in Cal.com and mint
    OUR single-tenant occupancy for the granted length — the backend owns how long
    the lab is actually held, so the tier applies even though Cal.com's slot is 1h."""
    email = (x_identity_email or "").strip().lower()
    if not email:
        raise HTTPException(401, "sign in to book")
    if authentik_sync.is_active_account(email) is False:
        raise HTTPException(403, "account is not an active lab member")

    def _int(v, d):
        try:
            return int(v)
        except (TypeError, ValueError):
            return d
    per_cap = _int(x_booking_max_min, 60)
    daily_cap = _int(x_booking_daily_min, 60)
    requested = _int((payload or {}).get("duration_min"), 60)

    start = (payload or {}).get("start") or calcom.next_slot_iso()
    start_epoch = calcom.parse_iso(start)
    d0, d1 = calcom.day_bounds(start_epoch)
    used = sessions.booked_minutes_on(email, d0, d1)
    remaining = daily_cap - used
    if remaining < 60:
        raise HTTPException(409, "You've used your lab time for that day — try another day.")

    dur = min(requested, per_cap, int(remaining), _ALLOWED_DUR[-1])
    dur = max(a for a in _ALLOWED_DUR if a <= dur)  # snap down to an allowed step

    name = (payload or {}).get("name") or ""
    try:
        res = calcom.book(email, name, start)  # holds the base slot + emails the booker
    except calcom.BookingError as e:
        if e.conflict:
            raise HTTPException(409, "That time isn't available — pick another slot.")
        raise HTTPException(502, "Booking service is unavailable right now.")

    start_epoch = calcom.parse_iso(res.get("start") or start)
    end_epoch = start_epoch + dur * 60
    sessions.mint("ise-lab-demo", email, end_epoch, starts_at=start_epoch, uid=res.get("uid", ""))
    try:  # promptly reflect the new occupant in the desktop group
        authentik_sync.reconcile(sessions.active_emails())
    except Exception:
        pass
    return {"ok": True, "start": res.get("start") or start,
            "end": calcom._iso(end_epoch), "duration_min": dur}


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
        # The enclave is golden-reset for each new occupant; don't let them drive it
        # until that hand-off reset has finished (the portal shows "preparing").
        if not tenancy.status_for(me)["ready"]:
            raise HTTPException(409, "Your lab is still being prepared — give it a moment.")
    # Manual reset routes through the background hand-off path (drop ownership so the
    # reconciler re-prepares) — reuses the "preparing" screen and the generous
    # background reset budget instead of the 240s proxy-bound synchronous reset.
    if action_id == "lab.reset":
        tenancy.request_manual_reset((x_identity_email or "").strip().lower())
        return {"action": action_id, "result": {"preparing": True}}
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
