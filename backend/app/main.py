"""Tier-2 FastAPI backend.

Exposes ONLY the allowlisted action registry to the portal, behind a role check
and guardrails. Demo visitors never reach this directly (network isolation); the
Tier-1 portal authenticates them and forwards the resolved role.

Auth here is intentionally a stub (X-Role / X-Session headers set by the trusted
portal). Real visitor/admin auth (Authelia + demo-session token) lands in Phase 6;
this service must only ever be reachable from the portal, never the internet.
"""
from fastapi import FastAPI, Header, HTTPException

from . import guardrails
from .actions import ACTIONS
from .proxmox import Proxmox, ProxmoxError

app = FastAPI(title="ise-lab-demo backend", docs_url=None, redoc_url=None)

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


@app.get("/api/actions")
def list_actions(x_role: str = Header("visitor")):
    return {
        aid: {"role": a.role, "mutating": a.mutating, "summary": a.summary}
        for aid, a in ACTIONS.items()
        if _authorized(x_role, a.role)
    }


@app.post("/api/action/{action_id}")
def run_action(action_id: str,
               x_role: str = Header("visitor"),
               x_session: str = Header("anon")):
    act = ACTIONS.get(action_id)
    if act is None:
        raise HTTPException(404, "unknown action")
    if not _authorized(x_role, act.role):
        raise HTTPException(403, f"action requires role '{act.role}'")
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
        return {"action": action_id, "result": act.fn(px(), {})}
    except ProxmoxError as e:
        raise HTTPException(502, str(e))
    finally:
        if act.mutating:
            guardrails.release()
