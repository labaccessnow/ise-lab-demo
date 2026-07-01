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


def _client_ip(request: Request) -> str:
    # The edge (BunkerWeb) sets X-Forwarded-For with the real visitor IP as the first
    # hop; fall back to the direct peer. The backend rate-limits mutating actions on
    # this, so a client can't dodge the cap by rotating a self-chosen session id.
    xff = request.headers.get("X-Forwarded-For", "")
    return (xff.split(",")[0].strip() if xff else "") or (request.client.host if request.client else "")


async def _proxy(method: str, path: str, sid: str, client_ip: str = "", json_body=None) -> JSONResponse:
    try:
        r = await _client.request(method, path,
                                  headers={"X-Role": _role(), "X-Session": sid, "X-Client-IP": client_ip},
                                  json=json_body)
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
async def actions(request: Request, sid: str = Cookie(None)):
    return await _proxy("GET", "/api/actions", sid or uuid.uuid4().hex, _client_ip(request))


@app.get("/api/catalog")
async def catalog(request: Request, sid: str = Cookie(None)):
    return await _proxy("GET", "/api/catalog", sid or uuid.uuid4().hex, _client_ip(request))


@app.get("/api/session/{token}")
async def session_check(token: str):
    # Validate a booking handoff token (presence + expiry) against the backend.
    return await _proxy("GET", f"/api/session/{token}", token)


@app.post("/api/session/claim")
async def session_claim(request: Request):
    """Redeem the ?session= booking token against the edge-verified identity.

    The identity comes ONLY from the trusted forward-auth header that the edge sets
    from the Authentik auth subrequest (X-Forwarded-Email) — never from the client
    body. The edge MUST strip any client-supplied copy of this header (see infra
    notes). On success the booking token is consumed and we set an httponly `sid`
    cookie = the server-minted session id; the token never goes back to the client.
    """
    email = request.headers.get("X-Forwarded-Email", "")
    try:
        body = await request.json()
    except Exception:
        body = {}
    token = (body or {}).get("token")
    try:
        r = await _client.post("/api/session/claim",
                               headers={"X-Identity-Email": email}, json={"token": token})
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"detail": f"backend unreachable: {e.__class__.__name__}"})
    try:
        data = r.json()
    except Exception:
        data = {"detail": "backend returned non-JSON"}
    if r.status_code != 200:
        return JSONResponse(status_code=r.status_code, content=data)
    resp = JSONResponse(status_code=200, content={"ok": True, "lab": data["lab_id"],
                                                  "expires_at": data["expires_at"]})
    resp.set_cookie("sid", data["server_sid"], httponly=True, samesite="lax", max_age=86400)
    return resp


@app.post("/api/action/{action_id}")
async def action(action_id: str, request: Request, sid: str = Cookie(None)):
    try:
        body = await request.json()
    except Exception:
        body = None
    return await _proxy("POST", f"/api/action/{action_id}", sid or uuid.uuid4().hex,
                        _client_ip(request), json_body=body)


@app.get("/healthz")
async def healthz():
    try:
        r = await _client.get("/healthz")
        return {"portal": True, "backend": r.json()}
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"portal": True, "backend_error": e.__class__.__name__})


# Static frontend last, so /api/* and /healthz match first.
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
