"""Tier-1 portal (BFF).

Serves the static visitor frontend and proxies the visitor's *allowlisted* action
requests to the trusted Tier-2 backend. This tier holds NOTHING — no Proxmox
token, no SOPS key, no SSH key, no route to the lab network. It resolves the
visitor's role (default ``visitor``) and forwards it as ``X-Role``; the backend
enforces the allowlist + guardrails. A compromised portal can therefore only ever
*ask* for actions that already exist, at the role a visitor is granted.

Real visitor/admin auth (Authelia + the booking demo-session token, proj-demo-booking
Phase 2) lands in front of this as a trusted header; never trust a client role.

Run:  uvicorn portal:app --host 0.0.0.0 --port 8080
Env:  BACKEND_URL (default http://127.0.0.1:8000) — the Tier-2 backend.
"""
import os
import uuid

import httpx
from fastapi import Cookie, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="ise-lab-demo portal", docs_url=None, redoc_url=None)
_client = httpx.AsyncClient(base_url=BACKEND, timeout=300.0)


def _role() -> str:
    # Visitor by default. An auth layer (Authelia / booking demo-session) may set a
    # higher role via a trusted server-side header — never from the client.
    return "visitor"


async def _proxy(method: str, path: str, sid: str, json_body=None) -> JSONResponse:
    try:
        r = await _client.request(method, path, headers={"X-Role": _role(), "X-Session": sid}, json=json_body)
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"detail": f"backend unreachable: {e.__class__.__name__}"})
    try:
        body = r.json()
    except Exception:
        body = {"detail": "backend returned non-JSON"}
    resp = JSONResponse(status_code=r.status_code, content=body)
    resp.set_cookie("sid", sid, httponly=True, samesite="lax", max_age=86400)
    return resp


@app.get("/api/actions")
async def actions(sid: str = Cookie(None)):
    return await _proxy("GET", "/api/actions", sid or uuid.uuid4().hex)


@app.get("/api/catalog")
async def catalog(sid: str = Cookie(None)):
    return await _proxy("GET", "/api/catalog", sid or uuid.uuid4().hex)


@app.post("/api/action/{action_id}")
async def action(action_id: str, request: Request, sid: str = Cookie(None)):
    try:
        body = await request.json()
    except Exception:
        body = None
    return await _proxy("POST", f"/api/action/{action_id}", sid or uuid.uuid4().hex, json_body=body)


@app.get("/healthz")
async def healthz():
    try:
        r = await _client.get("/healthz")
        return {"portal": True, "backend": r.json()}
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"portal": True, "backend_error": e.__class__.__name__})


# Static frontend last, so /api/* and /healthz match first.
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
