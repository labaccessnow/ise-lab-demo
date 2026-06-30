"""Tier-2 FastAPI backend.

Exposes ONLY the allowlisted action registry to the portal, behind a role check
and guardrails. Demo visitors never reach this directly (network isolation); the
Tier-1 portal authenticates them and forwards the resolved role.

Auth here is intentionally a stub (X-Role / X-Session headers set by the trusted
portal). Real visitor/admin auth (Authelia + demo-session token) lands in Phase 6;
this service must only ever be reachable from the portal, never the internet.
"""
from fastapi import Body, FastAPI, Header, HTTPException

from . import catalog, guardrails, sessions
from .actions import ACTIONS, LabUnavailable
from .actions import maintenance_on as actions_maintenance_on
from .devices import DeviceError
from .proxmox import Proxmox, ProxmoxError
from .webhook import router as webhook_router

app = FastAPI(title="ise-lab-demo backend", docs_url=None, redoc_url=None)
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
               x_session: str = Header("anon")):
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
    try:
        guardrails.rate_check(x_session)
    except guardrails.RateLimited as e:
        raise HTTPException(429, str(e))

    if act.mutating:
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
